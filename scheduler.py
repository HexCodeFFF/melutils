import json

import discord
from aioscheduler import TimedScheduler
import aiosqlite
from datetime import datetime, timezone

from discord.ext import commands

from clogs import logger

scheduler = TimedScheduler(prefer_utc=True)
botcopy = commands.Bot


class ScheduleInitCog(commands.Cog):
    def __init__(self, bot):
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
                    logger.debug(f"Running missed event #{event[0]}")
                    await run_event(event[0], event[2], data)
                else:
                    logger.debug(f"scheduling stored event #{event[0]}")
                    scheduler.schedule(run_event(event[0], event[2], data), dt.replace(tzinfo=None))


async def run_event(dbrowid, eventtype: str, eventdata: dict):
    logger.debug(f"Running Event #{dbrowid} type {eventtype} data {eventdata}")
    if eventtype == "message":
        pass
        # await botcopy.get_channel(eventsubject).send(message)
    if dbrowid is not None:
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("DELETE FROM schedule WHERE id=?", (dbrowid,))
            await db.commit()


async def schedule(time: datetime, eventtype: str, eventdata: dict):
    assert time.tzinfo is not None
    if time <= datetime.now(tz=timezone.utc):
        logger.debug(f"running event without schedule type {eventtype} data {eventdata}")
        await run_event(None, eventtype, eventdata)

    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("INSERT INTO schedule (eventtime, eventtype, eventdata) VALUES (?,?,?)",
                              (time.timestamp(), eventtype, json.dumps(eventdata))) as cursor:
            lri = cursor.lastrowid
            timef = time.replace(tzinfo=timezone.utc).replace(tzinfo=None)
            scheduler.schedule(run_event(lri, eventtype, eventdata), timef)
            logger.debug(f"scheduled event #{lri} for {time}")
        await db.commit()
