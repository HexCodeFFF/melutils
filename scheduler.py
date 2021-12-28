import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
import humanize
import nextcord as discord
from aioscheduler import TimedScheduler
from nextcord.ext import commands

import modlog
from clogs import logger

scheduler = TimedScheduler(prefer_utc=True)
botcopy: commands.Bot
loadedtasks = dict()  # keep track of task objects to cancel if needed.


class ScheduleInitCog(commands.Cog):
    def __init__(self, bot):
        global botcopy
        botcopy = bot
        self.bot = bot
        bot.loop.create_task(start())


async def start():
    logger.debug("starting scheduler")
    scheduler.start()
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT id, eventtime, eventtype, eventdata FROM schedule") as cursor:
            async for event in cursor:
                data = json.loads(event[3])
                dt = datetime.fromtimestamp(event[1], tz=timezone.utc)
                if dt <= datetime.now(tz=timezone.utc):
                    logger.debug(f"running missed event #{event[0]}")
                    loadedtasks[event[0]] = task  # not needed but easier to put this here than to ignore the exception
                    await run_event(event[0], event[2], data)
                else:
                    logger.debug(f"scheduling stored event #{event[0]}")
                    task = scheduler.schedule(run_event(event[0], event[2], data), dt.replace(tzinfo=None))
                    loadedtasks[event[0]] = task


async def run_event(dbrowid, eventtype: str, eventdata: dict):
    try:
        logger.debug(f"Running Event #{dbrowid} type {eventtype} data {eventdata}")
        if dbrowid is not None:
            async with aiosqlite.connect("database.sqlite") as db:
                await db.execute("DELETE FROM schedule WHERE id=?", (dbrowid,))
                await db.commit()
        del loadedtasks[dbrowid]
        if eventtype == "debug":
            logger.debug("Hello world! (debug event)")
        elif eventtype == "message":
            ch = eventdata["channel"]
            try:
                ch = await botcopy.fetch_channel(ch)
            except discord.errors.NotFound:
                ch = await botcopy.fetch_user(ch)
            await ch.send(eventdata["message"])
        elif eventtype == "unban":
            guild, member = await asyncio.gather(botcopy.fetch_guild(eventdata["guild"]),
                                                 botcopy.fetch_user(eventdata["member"]))
            await asyncio.gather(guild.unban(member, reason="End of temp-ban."),
                                 member.send(f"You were unbanned in **{guild.name}**."),
                                 modlog.modlog(f"{member.mention} (`{member}`) "
                                               f"was automatically unbanned.", guild.id, member.id))
        elif eventtype == "unmute":
            # purely cosmetic
            guild = await botcopy.fetch_guild(eventdata["guild"])
            member = await guild.fetch_member(eventdata["member"])
            await asyncio.gather(member.send(f"You were unmuted in **{guild.name}**."),
                                 modlog.modlog(f"{member.mention} (`{member}`) "
                                               f"was automatically unmuted.", guild.id, member.id))
        elif eventtype == "refresh_mute":
            guild = await botcopy.fetch_guild(eventdata["guild"])
            member = await guild.fetch_member(eventdata["member"])
            if eventdata["muteend"] is None:
                await member.edit(timeout=datetime.now(tz=timezone.utc) + timedelta(days=28))
                await schedule(datetime.now(tz=timezone.utc) + timedelta(days=28), "refresh_mute",
                               {"guild": member.guild.id, "member": member.id, "muteend": None})
                logger.debug(f"Refreshed {member}'s permanent mute in {guild}")
            else:
                muteend = datetime.fromtimestamp(eventdata["muteend"], tz=timezone.utc)
                if muteend - datetime.now(tz=timezone.utc) > timedelta(days=28):
                    await member.edit(timeout=datetime.now(tz=timezone.utc) + timedelta(days=28))
                    await schedule(datetime.now(tz=timezone.utc) + timedelta(days=28),
                                   "refresh_mute",
                                   {"guild": member.guild.id, "member": member.id, "muteend": eventdata["muteend"]})
                    logger.debug(f"Refreshed {member}'s mute in {guild}. ends {muteend}")
                else:
                    await member.edit(timeout=muteend)
                    await schedule(muteend, "unmute", {"guild": member.guild.id, "member": member.id})
                    logger.debug(f"Refreshed {member}'s mute for the last time in {guild}. ends {muteend}")

        elif eventtype == "un_thin_ice":
            guild = await botcopy.fetch_guild(eventdata["guild"])
            member = await guild.fetch_member(eventdata["member"])
            await asyncio.gather(member.remove_roles(discord.Object(eventdata["thin_ice_role"])),
                                 member.send(f"Your thin ice has expired in **{guild.name}**."),
                                 modlog.modlog(f"{member.mention}'s (`{member}`) "
                                               f"thin ice has expired.", guild.id, member.id))
            async with aiosqlite.connect("database.sqlite") as db:
                await db.execute("DELETE FROM thin_ice WHERE guild=? and user=?", (guild.id, member.id))
                await db.commit()
        elif eventtype == "birthday":
            async with aiosqlite.connect("database.sqlite") as db:
                now = datetime.now(tz=timezone.utc)
                birthday = datetime.fromtimestamp(eventdata["birthday"], tz=timezone.utc)
                age = round((now - birthday).days / 365.25)
                createdchannels = []
                for guild in botcopy.guilds:
                    async with db.execute("SELECT birthday_category FROM server_config WHERE guild=?",
                                          (guild.id,)) as cur:
                        bcategory = await cur.fetchone()
                    if bcategory is not None:
                        member = guild.get_member(eventdata["user"])
                        bcategoryreal: discord.CategoryChannel = guild.get_channel(bcategory[0])
                        if bcategoryreal is not None and member is not None:
                            dname = ''.join(c for c in member.display_name.lower() if c.isalnum() or c == "-")
                            bchannel = await bcategoryreal.create_text_channel(f"🎂{dname}-birthday"[:32],
                                                                               reason=f"{member.display_name}"
                                                                                      f"'s birthday.")
                            createdchannels.append(bchannel.id)
                            await bchannel.send(f"Happy {humanize.ordinal(age)} Birthday {member.mention}!!",
                                                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
                # schedule next birthday event
                thisyear = now.year
                nextbirthday = birthday
                while nextbirthday < now:
                    try:
                        nextbirthday = nextbirthday.replace(year=thisyear)
                    except ValueError as e:  # leap years are weird
                        logger.debug(str(e))
                    thisyear += 1
                await schedule(nextbirthday, "birthday", {"user": eventdata["user"], "birthday": birthday.timestamp()})
                # delete birthday channels in 24 hours
                await schedule(now + timedelta(days=1), "delbirthdaychannel", {"channels": createdchannels})
        elif eventtype == "delbirthdaychannel":
            for ch in eventdata["channels"]:
                channel = botcopy.get_channel(ch)
                await channel.delete(reason="Birthday is over")
        else:
            logger.error(f"Unknown event type {eventtype} for event {dbrowid}")

    except Exception as e:
        logger.error(e, exc_info=(type(e), e, e.__traceback__))


async def schedule(time: datetime, eventtype: str, eventdata: dict):
    assert time.tzinfo is not None  # offset aware datetimes my beloved
    if time <= datetime.now(tz=timezone.utc):
        logger.debug(f"running event now")
        await run_event(None, eventtype, eventdata)

    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("INSERT INTO schedule (eventtime, eventtype, eventdata) VALUES (?,?,?)",
                              (time.timestamp(), eventtype, json.dumps(eventdata))) as cursor:
            lri = cursor.lastrowid
            timef = time.astimezone(tz=timezone.utc).replace(tzinfo=None)
            task = scheduler.schedule(run_event(lri, eventtype, eventdata), timef)
            loadedtasks[lri] = task
            logger.debug(f"scheduled event #{lri} for {time}")
            # logger.debug(loadedtasks)
        await db.commit()
    return lri


async def canceltask(dbrowid: int, db: Optional[aiosqlite.Connection] = None):
    scheduler.cancel(loadedtasks[dbrowid])
    if db is None:
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("DELETE FROM schedule WHERE id=?", (dbrowid,))
            await db.commit()
    else:
        await db.execute("DELETE FROM schedule WHERE id=?", (dbrowid,))
        await db.commit()
    # it throws a runtime warning "coroutine was never ran" like no shit that is the entire idea
    # TODO: suppress this mf!!
    del loadedtasks[dbrowid]
    logger.debug(f"Cancelled task {dbrowid}")
