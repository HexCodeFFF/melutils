import asyncio
import time
import typing
from datetime import datetime, timedelta, timezone
from numbers import Number

import aiosqlite
import discord
from discord.ext import commands
from discord.ext.commands import Greedy

import humanize
import modlog
import scheduler
from clogs import logger
from timeconverter import TimeConverter


def mod_only():
    async def extended_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        if ctx.author.guild_permissions.manage_guild:
            return True
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT mod_role FROM server_config WHERE guild=?", (ctx.guild.id,)) as cur:
                modrole = await cur.fetchone()
        if modrole is None:
            raise commands.CheckFailure("Server has no moderator role set up. Ask an admin to add one.")
        modrole = modrole[0]
        if modrole in [r.id for r in ctx.author.roles]:
            return True
        raise commands.CheckFailure(
            "You need to have the moderator role or Manage Server permissions to run this command.")

    return commands.check(extended_check)


async def update_server_config(server: int, config: str, value):
    """DO NOT ALLOW CONFIG TO BE logger.debug("pass")ED AS A VARIABLE, PRE-DEFINED STRINGS ONLY."""
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT COUNT(guild) FROM server_config WHERE guild=?", (server,)) as cur:
            guilds = await cur.fetchone()
        if guilds[0]:  # if there already is a row for this guild
            await db.execute(f"UPDATE server_config SET {config} = ? WHERE guild=?", (value, server))
        else:  # if not, make one
            await db.execute(f"INSERT INTO server_config(guild, {config}) VALUES (?, ?)", (server, value))
        await db.commit()


async def set_up_muted_role(guild: discord.Guild):
    logger.debug(f"SETTING UP MUTED ROLE FOR {guild}")
    logger.debug("deleting existing role(s)")
    roletask = [role.delete(reason='Setting up mute system.') for role in guild.roles if
                role.name == "[MelUtils] muted"]
    await asyncio.gather(*roletask)
    logger.debug("creating new role")
    muted_role = await guild.create_role(name="[MelUtils] muted", reason='Setting up mute system.')
    logger.debug("overriding permissions on all channels")
    await asyncio.gather(
        *[channel.set_permissions(muted_role, send_messages=False, speak=False, reason='Setting up mute system.')
          for channel in guild.channels + guild.categories])
    logger.debug("setting config")
    await update_server_config(guild.id, "muted_role", muted_role.id)
    return muted_role

    # async with aiosqlite.connect("database.sqlite") as db:
    #     async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (guild.id,)) as cur:


async def get_muted_role(guild: discord.Guild) -> discord.Role:
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (guild.id,)) as cur:
            mutedrole = await cur.fetchone()
    if mutedrole is None or mutedrole[0] is None:
        muted_role = await set_up_muted_role(guild)
    else:
        muted_role = guild.get_role(mutedrole[0])
        if muted_role is None:
            muted_role = await set_up_muted_role(guild)
    return muted_role


async def ban_action(member: discord.User, ban_length: typing.Optional[timedelta], reason: str):
    bans = [ban.user for ban in await member.guild.bans()]
    if member in bans:
        return False
    htime = humanize.precisedelta(ban_length)
    try:
        await member.guild.ban(member, reason=reason, delete_message_days=0)
        if ban_length is None:
            try:
                await member.send(f"You were permanently banned in **{member.guild.name}** with reason "
                                  f"`{discord.utils.escape_mentions(reason)}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        else:
            scheduletime = datetime.now(tz=timezone.utc) + ban_length
            await scheduler.schedule(scheduletime, "unban", {"guild": member.guild.id, "member": member.id})
            try:
                await member.send(f"You were banned in **{member.guild.name}** for **{htime}** with reason "
                                  f"`{discord.utils.escape_mentions(reason)}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        return True
    except discord.Forbidden:
        await modlog.modlog(f"Tried to ban {member.mention} (`{member}`) "
                            f"but I wasn't able to! Are they an admin?",
                            member.guild.id, member.id)


async def mute_action(member: discord.Member, mute_length: typing.Optional[timedelta], reason: str):
    muted_role = await get_muted_role(member.guild)
    if muted_role in member.roles:
        return False
    htime = humanize.precisedelta(mute_length)
    await member.add_roles(muted_role, reason=reason)
    if mute_length is None:
        try:
            await member.send(f"You were permanently muted in **{member.guild.name}** with reason "
                              f"`{discord.utils.escape_mentions(reason)}`.")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            logger.debug("pass")
    else:
        scheduletime = datetime.now(tz=timezone.utc) + mute_length
        await scheduler.schedule(scheduletime, "unmute",
                                 {"guild": member.guild.id, "member": member.id, "mute_role": muted_role.id})
        try:
            await member.send(f"You were muted in **{member.guild.name}** for **{htime}** with reason "
                              f"`{discord.utils.escape_mentions(reason)}`.")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            logger.debug("pass")
    return True


async def on_warn(member: discord.Member, issued_points: float):
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                              (member.guild.id,)) as cur:
            thin_ice_role = await cur.fetchone()
        if thin_ice_role is not None and thin_ice_role[0] is not None and thin_ice_role[0] in [role.id for role in
                                                                                               member.roles]:
            await db.execute("UPDATE thin_ice SET warns_on_thin_ice = warns_on_thin_ice+? WHERE guild=? AND user=?",
                             (issued_points, member.guild.id, member.id))
            await db.commit()
            threshold = thin_ice_role[1]
            async with db.execute("SELECT warns_on_thin_ice FROM thin_ice WHERE guild=? AND user=?",
                                  (member.guild.id, member.id)) as cur:
                warns_on_thin_ice = (await cur.fetchone())[0]
            if warns_on_thin_ice >= threshold:
                await ban_action(member, None, f"Automatically banned for receiving more than {threshold}"
                                               f" points on thin ice.")
                await modlog.modlog(f"{member.mention} (`{member}`) was automatically "
                                    f"banned for receiving more than {threshold} "
                                    f"points on thin ice.", member.guild.id, member.id)
                await db.execute("UPDATE thin_ice SET warns_on_thin_ice = 0 WHERE guild=? AND user=?",
                                 (member.guild.id, member.id))
                await db.commit()

        else:
            # select all from punishments where the sum of warnings in the punishment range fits the warn_count thing
            # this thing is a mess but should return 1 or 0 punishments if needed
            monstersql = "SELECT *, (SELECT SUM(points) FROM warnings WHERE (warn_timespan=0 OR (" \
                         ":now-warn_timespan)<warnings.issuedat) AND warnings.server=:guild AND user=:user AND " \
                         "deactivated=0) pointstotal FROM auto_punishment WHERE pointstotal >= warn_count AND " \
                         "warn_count > (pointstotal-:pointsjustgained) AND guild=:guild ORDER BY punishment_duration," \
                         "punishment_type DESC LIMIT 1 "
            params = {"now": datetime.now(tz=timezone.utc).timestamp(), "pointsjustgained": issued_points,
                      "guild": member.guild.id, "user": member.id}
            async with db.execute(monstersql, params) as cur:
                punishment = await cur.fetchone()
            if punishment is not None:
                logger.debug(punishment)
                punishment_types = {
                    "ban": ban_action,
                    "mute": mute_action
                }
                func = punishment_types[punishment[2]]
                duration = None if punishment[3] == 0 else timedelta(seconds=punishment[3])
                timespan_text = "total" if punishment[4] == 0 else \
                    f"within {humanize.precisedelta(punishment[4])}"
                await func(member, duration,
                           f"Automatic punishment due to reaching {punishment[1]} points {timespan_text}")
                punishment_type_future_tense = {
                    "ban": "banned",
                    "mute": "muted"
                }
                punishment_text = "permanently" if duration.total_seconds() == 0 else \
                    f"for {humanize.precisedelta(duration)}"
                await modlog.modlog(
                    f"{member.mention} (`{member}`) has been automatically {punishment_type_future_tense[punishment[2]]} "
                    f" {punishment_text} due to reaching {punishment[1]} points {timespan_text}",
                    member.guild.id, member.id)


class ModerationCog(commands.Cog, name="Moderation"):
    """
    commands for server moderation
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if len(message.mentions) > 10 and message.guild:
            await asyncio.gather(
                message.delete(),
                ban_action(message.author, None, "Automatically banned for mass ping."),
                modlog.modlog(f"{message.author.mention} (`{message.author}`) "
                              f"was automatically banned for mass ping.", message.guild.id, message.author.id)
            )
        if message.guild and isinstance(message.author, discord.Member):
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (message.guild.id,)) as cur:
                    mutedrole = await cur.fetchone()
            if mutedrole is not None and mutedrole[0] is not None:
                if mutedrole[0] in [role.id for role in message.author.roles]:
                    await message.delete()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (channel.guild.id,)) as cur:
                mutedrole = await cur.fetchone()
        if mutedrole is not None and mutedrole[0] is not None:
            muted_role = channel.guild.get_role(mutedrole[0])
            await channel.set_permissions(muted_role, send_messages=False, speak=False,
                                          reason='Setting up mute system.')

    # delete unban events if someone manually unbans with discord.
    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        actuallycancelledanytasks = False
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                  "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                  (guild.id, user.id, "unban")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])
                    actuallycancelledanytasks = True
            async with db.execute("SELECT thin_ice_role FROM server_config WHERE guild=?", (guild.id,)) as cur:
                thin_ice_role = await cur.fetchone()
            if thin_ice_role is not None and thin_ice_role[0] is not None:
                await db.execute("REPLACE INTO thin_ice(user,guild,marked_for_thin_ice,warns_on_thin_ice) VALUES "
                                 "(?,?,?,?)", (user.id, guild.id, True, 0))
                await db.commit()
        if actuallycancelledanytasks:
            try:
                await user.send(f"You were manually unbanned in **{guild.name}**.")
            except (discord.Forbidden, discord.HTTPException, AttributeError, discord.NotFound):
                logger.debug("pass")
        channel_to_invite = guild.text_channels[0]
        invite = await channel_to_invite.create_invite(max_uses=1, reason=f"{user.name} was unbanned.")
        try:
            await user.send(f"You can rejoin **{guild.name}** with this link: {invite}")
        except (discord.Forbidden, discord.HTTPException, AttributeError, discord.NotFound):
            logger.debug("pass")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                  "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                  (guild.id, user.id, "un_thin_ice")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])
            async with db.execute("SELECT ban_appeal_link FROM server_config WHERE guild=?", (guild.id,)) as cur:
                ban_appeal_link = await cur.fetchone()
        if ban_appeal_link is not None and ban_appeal_link[0] is not None:
            try:
                await user.send(f"You can appeal your ban from **{guild.name}** at {ban_appeal_link[0]}")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")

    # delete unmute events if someone removed the role manually with discord
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        muted_role = await get_muted_role(after.guild)
        if muted_role in before.roles and muted_role not in after.roles:  # if muted role manually removed
            actuallycancelledanytasks = False
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (after.guild.id, after.id, "unmute")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])
                        actuallycancelledanytasks = True
            if actuallycancelledanytasks:
                await after.send(f"You were manually unmuted in **{after.guild.name}**.")
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT thin_ice_role FROM server_config WHERE guild=?",
                                  (after.guild.id,)) as cur:
                thin_ice_role = await cur.fetchone()
            if thin_ice_role is not None and thin_ice_role[0] is not None:
                if thin_ice_role[0] in [role.id for role in before.roles] and thin_ice_role[0] not in [role.id for role
                                                                                                       in
                                                                                                       after.roles]:  # if muted role manually removed
                    actuallycancelledanytasks = False
                    async with aiosqlite.connect("database.sqlite") as db:
                        async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                              "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                              (after.guild.id, after.id, "un_thin_ice")) as cur:
                            async for row in cur:
                                await scheduler.canceltask(row[0])
                                actuallycancelledanytasks = True
                    if actuallycancelledanytasks:
                        await after.send(f"Your thin ice was manually removed in **{after.guild.name}**.")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                                  (member.guild.id,)) as cur:
                thin_ice_role = await cur.fetchone()
            if thin_ice_role is not None and thin_ice_role[0] is not None:
                async with db.execute("SELECT * from thin_ice WHERE user=? AND guild=? AND marked_for_thin_ice=1",
                                      (member.id, member.guild.id)) as cur:
                    user = await cur.fetchone()
                if user is not None:
                    await member.add_roles(discord.Object(thin_ice_role[0]))
                    scheduletime = datetime.now(tz=timezone.utc) + timedelta(weeks=1)
                    await scheduler.schedule(scheduletime, "un_thin_ice",
                                             {"guild": member.guild.id, "member": member.id,
                                              "thin_ice_role": thin_ice_role[0]})
                    await member.send(f"Welcome back to **{member.guild.name}**. since you were just unbanned, you will"
                                      f" have the **thin ice** role for **1 week.** If you receive {thin_ice_role[1]} "
                                      f"point(s) in this timespan, you will be permanently banned.")

    @commands.command(aliases=["setmodrole", "addmodrole", "moderatorrole"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def modrole(self, ctx, *, role: typing.Optional[discord.Role] = None):
        """
        Sets the server moderator role.
        Anyone who has the mod role can use commands such as mute and warn.

        :Param=role - The moderator role, leave blank to remove the modrole from this server
        """
        if role is None:
            await update_server_config(ctx.guild.id, "mod_role", None)
            await ctx.reply("✔️ Removed server moderator role.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the server mod role.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "mod_role", role.id)
            await ctx.reply(f"✔️ Set server moderator role to **{discord.utils.escape_mentions(role.name)}**")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"server mod role to {role.mention}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["setthinicerole", "addthinicerole", "setthinice"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def thinicerole(self, ctx, *, role: typing.Optional[discord.Role] = None):
        """
        Sets the server thin ice role and activates the thin ice system.
        Anyone who has the mod role can use commands such as mute and warn.

        :Param=role - The thin ice role, leave blank to remove the thin ice system from this server
        """
        if role is None:
            await update_server_config(ctx.guild.id, "thin_ice_role", None)
            await ctx.reply("✔️ Removed server thin ice role.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the server mod role.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "thin_ice_role", role.id)
            await ctx.reply(f"✔️ Set server thin ice role to **{discord.utils.escape_mentions(role.name)}**")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"server thin ice role to {role.mention}", ctx.guild.id, modid=ctx.author.id)

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def thinicethreshold(self, ctx, *, threshold: int = 1):
        """
        Sets the amount of points someone has to get on thin ice to be permanently banned.

        :Param=threshold - the amount of points someone has to get on thin ice to be permanently banned.
        """
        assert threshold >= 1
        await update_server_config(ctx.guild.id, "thin_ice_threshold", threshold)
        await ctx.reply(f"✔️ Set server thin ice threshold to **{threshold} point(s)**")
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                            f"server thin ice threshold to **{threshold} point(s)**",
                            ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["setlogchannel", "modlogchannel", "moderatorlogchannel", "setmodlogchannel",
                               "setmodlog"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def logchannel(self, ctx, *, ch: typing.Optional[discord.TextChannel] = None):
        """
        Sets the server modlog channel.
        All moderator actions will be logged in this channel.

        :Param=channel - The modlog channel, leave blank to remove the modlog from this server
        """
        if ch is None:
            await update_server_config(ctx.guild.id, "log_channel", None)
            await ctx.reply("✔️ Removed server modlog channel.")
        else:
            await update_server_config(ctx.guild.id, "log_channel", ch.id)
            await ctx.reply(f"✔️ Set server modlog channel to **{discord.utils.escape_mentions(ch.mention)}**")
            await ch.send(f"This is the new modlog channel for {ctx.guild.name}!")

    @commands.command(aliases=["banappeal"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def banappeallink(self, ctx, *, ban_appeal_link=None):
        """
        Sets the server modlog channel.
        All moderator actions will be logged in this channel.

        :Param=channel - The ban appeal link, leave blank to remove the modlog from this server
        """
        if ban_appeal_link is None:
            await update_server_config(ctx.guild.id, "ban_appeal_link", None)
            await ctx.reply("✔️ Removed server ban appeal link.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the ban appeal link.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "ban_appeal_link", ban_appeal_link)
            await ctx.reply(f"✔️ Set server ban appeal link to **{discord.utils.escape_mentions(ban_appeal_link)}** .")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"ban appeal link to {ban_appeal_link}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["b"])
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def ban(self, ctx, members: Greedy[discord.User],
                  ban_length: typing.Optional[TimeConverter] = None, *,
                  reason: str = "No reason provided."):
        """
        Ban/temp-ban a member or several.

        :Param=members - one or more members to ban
        :Param=ban_length (optional) - how long to ban them for. don't specify for a permanent ban.
        :Param=reason (optional) - why the user was banned.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        htime = humanize.precisedelta(ban_length)
        for member in members:
            result = await ban_action(member, ban_length, reason)
            if not result:
                await ctx.reply(f"❌ {member.mention} is already banned!")
                continue
            if ban_length is None:
                await ctx.reply(
                    f"✔ Permanently banned **{member.mention}** with reason `{discord.utils.escape_mentions(reason)}️`")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) banned"
                                    f" {member.mention} (`{member}`) with reason "
                                    f"`{discord.utils.escape_mentions(reason)}️`", ctx.guild.id, member.id,
                                    ctx.author.id)
            else:
                await ctx.reply(f"✔️ Banned **{member.mention}** for **{htime}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) banned"
                                    f" {member.mention} (`{member}`) for {htime} with reason "
                                    f"`{discord.utils.escape_mentions(reason)}`.", ctx.guild.id, member.id,
                                    ctx.author.id)

    @commands.command(aliases=["mu"])
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def mute(self, ctx, members: Greedy[discord.Member],
                   mute_length: typing.Optional[TimeConverter] = None, *,
                   reason: str = "No reason provided."):
        """
        Mute or tempmute a member or several.

        :Param=members - one or more members to mute
        :Param=mute_length (optional) - how long to mute them for. don't specify for a permanent mute.
        :Param=reason (optional) - why the user was muted.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        htime = humanize.precisedelta(mute_length)
        for member in members:
            result = await mute_action(member, mute_length, reason)
            if not result:
                await ctx.reply(f"❌ {member.mention} is already muted!")
                continue
            if mute_length is None:
                await ctx.reply(
                    f"✔ Permanently muted **{member.mention}** with reason `{discord.utils.escape_mentions(reason)}️`")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                    f"permanently muted {member.mention} (`{member}`) "
                                    f"with reason "
                                    f"{discord.utils.escape_mentions(reason)}️`", ctx.guild.id, member.id,
                                    ctx.author.id)
            else:
                await ctx.reply(f"✔️ Muted **{member.mention}** for **{htime}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) muted "
                                    f"{member.mention} (`{member}`) for **{htime}**"
                                    f" with reason "
                                    f"`{discord.utils.escape_mentions(reason)}`.", ctx.guild.id, member.id,
                                    ctx.author.id)

    @commands.command(aliases=["um"])
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def unmute(self, ctx, members: Greedy[discord.Member]):
        """
        Unmute one or more members

        :Param=members - one or more members to unmute.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        muted_role = await get_muted_role(ctx.guild)
        async with aiosqlite.connect("database.sqlite") as db:
            for member in members:
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (ctx.guild.id, member.id, "unmute")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])
                        await member.remove_roles(muted_role)

                await ctx.reply(f"✔️ Unmuted {member.mention}")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) unmuted"
                                    f" {member.mention} (`{member}`)", ctx.guild.id, member.id, ctx.author.id)
                try:
                    await member.send(f"You were manually unmuted in **{ctx.guild.name}**.")
                except (discord.Forbidden, discord.HTTPException, AttributeError):
                    logger.debug("pass")

    @commands.command(aliases=["ub"])
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def unban(self, ctx, members: Greedy[discord.User]):
        """
        Unban one or more members

        :Param=members - one or more members to unban.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        # muted_role = await get_muted_role(ctx.guild)
        bans = [ban.user for ban in await ctx.guild.bans()]
        async with aiosqlite.connect("database.sqlite") as db:
            for member in members:
                if member not in bans:
                    await ctx.reply(f"❌ {member.mention} isn't banned!")
                    continue
                await ctx.guild.unban(member)
                await ctx.reply(f"✔️ Unbanned {member.mention}")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                    f"unbanned {member.mention} (`{member}`)",
                                    ctx.guild.id, member.id, ctx.author.id)
                try:
                    await member.send(f"You were manually unbanned in **{ctx.guild.name}**.")
                except (discord.Forbidden, discord.HTTPException, AttributeError):
                    logger.debug("pass")
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (ctx.guild.id, member.id, "unban")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])

    @commands.command(aliases=["deletewarn", "removewarn", "dwarn", "cancelwarn", "dw"])
    @mod_only()
    async def delwarn(self, ctx, warn_ids: Greedy[int]):
        """
        Delete a warning.

        :Param=warn_ids - one or more warn IDs to delete. get the ID of a warn with m.warns.
        """
        for warn_id in warn_ids:
            async with aiosqlite.connect("database.sqlite") as db:
                cur = await db.execute("UPDATE warnings SET deactivated=1 WHERE id=? AND server=? AND deactivated=0",
                                       (warn_id, ctx.guild.id))
                await db.commit()
            if cur.rowcount > 0:
                await ctx.reply(f"✔️ Removed warning #{warn_id}")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                    f"removed warning #{warn_id}", ctx.guild.id, modid=ctx.author.id)
            else:
                await ctx.reply(f"❌ Failed to remove warning. Does warn #{warn_id} exist and is it from this server?")

    @commands.command(aliases=["restorewarn", "undeletewarn", "udw"])
    @mod_only()
    async def undelwarn(self, ctx, warn_id: int):
        """
        Undelete a warning.

        :Param=warn_ids - one or more warn IDs to restore. get the ID of a warn with m.warns.
        """
        async with aiosqlite.connect("database.sqlite") as db:
            cur = await db.execute("UPDATE warnings SET deactivated=0 WHERE id=? AND server=? AND deactivated=1",
                                   (warn_id, ctx.guild.id))
            await db.commit()
        if cur.rowcount > 0:
            await ctx.reply(f"✔️ Restored warning #{warn_id}")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                f"restored warning #{warn_id}", ctx.guild.id, modid=ctx.author.id)
        else:
            await ctx.reply(f"❌ Failed to unremove warning. Does warn #{warn_id} exist and is it from this server?")

    @commands.command(aliases=["w"])
    @mod_only()
    async def warn(self, ctx, member: discord.Member, points: typing.Optional[float] = 1, *,
                   reason="No reason provided."):
        """
        Warn a member.

        :Param=member - the member to warn.
        :Param=points (optional, default 1) - the amount of points this warn is worth. think of it as a warn weight.
        :Param=reason (optional) - the reason for warning the member.
        """
        assert points >= 0
        if points > 1:
            points = round(points, 1)
        now = datetime.now(tz=timezone.utc)
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, member.id, ctx.author.id,
                              int(now.timestamp()), reason, points))
            await db.commit()
        await ctx.reply(f"Warned {member.mention} with {points} infraction point{'' if points == 1 else 's'} for: "
                        f"`{discord.utils.escape_mentions(reason)}`")
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                            f"warned {member.mention} (`{member}`) with {points}"
                            f" infraction point{'' if points == 1 else 's'} for: "
                            f"`{discord.utils.escape_mentions(reason)}`", ctx.guild.id, member.id, ctx.author.id)
        try:
            await member.send(f"You were warned in {ctx.guild.name} for `{discord.utils.escape_mentions(reason)}`.")
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            logger.debug("pass")
        await on_warn(member, points)  # this handles autopunishments

    @commands.command(aliases=["ow", "transferwarn"])
    @mod_only()
    async def oldwarn(self, ctx, member: discord.Member, day: int, month: int, year: int,
                      points: typing.Optional[float] = 1, *, reason="No reason provided."):
        """
        Creates a warn for a member issued at a custom date. Useful for transferring old warns.

        :Usage=m.oldwarn `member` `dd` `mm` `yyyy` `(points)` `(reason)`
        :Param=member - the member to warn.
        :Param=day - part of the date
        :Param=month - part of the date
        :Param=year - part of the date
        :Param=points (optional, default 1) - the amount of points this warn is worth. think of it as a warn weight.
        :Param=reason (optional) - the reason for warning the member.
        """
        assert points > 0
        if points > 1:
            points = round(points, 1)
        now = datetime(day=day, month=month, year=year, tzinfo=timezone.utc)
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, member.id, ctx.author.id,
                              int(now.timestamp()), reason, points))
            await db.commit()
        await ctx.reply(
            f"Created warn on {humanize.naturaldate(now)} for {member.mention} with {points} infraction "
            f"point{'' if points == 1 else 's'} for: `{discord.utils.escape_mentions(reason)}`")
        await modlog.modlog(
            f"{ctx.author.mention} (`{ctx.author}`) created warn on "
            f"{humanize.naturaldate(now)} for {member.mention} (`{member}`) with"
            f" {points} "
            f"infraction point{'' if points == 1 else 's'} for: "
            f"`{discord.utils.escape_mentions(reason)}`", ctx.guild.id, member.id, ctx.author.id)
        # try:
        #     await member.send(f"You were warned in {ctx.guild.name} for `{discord.utils.escape_mentions(reason)}`.")
        # except (discord.Forbidden, discord.HTTPException, AttributeError):
        #     logger.debug("pass")
        await on_warn(member, points)  # this handles autopunishments

    @commands.command(aliases=["warnings", "listwarns", "listwarn", "ws"])
    @mod_only()
    async def warns(self, ctx, member: discord.Member, page: int = 1, show_deleted: bool = False):
        """
        List a member's warns.

        :Param=member - the member to see the warns of.
        :Param=page (optional, default 1) - if the user has more than 25 warns, this will let you see pages of warns.
        :Param=show_deleted (optional, default no) - show deleted warns.
        """
        assert page > 0
        embed = discord.Embed(title=f"Warns for {member.display_name}: Page {page}", color=discord.Color(0xB565D9),
                              description=member.mention)
        async with aiosqlite.connect("database.sqlite") as db:
            deactivated_text = "" if show_deleted else "AND deactivated=0"
            async with db.execute(f"SELECT id, issuedby, issuedat, reason, deactivated, points FROM warnings "
                                  f"WHERE user=? AND server=? {deactivated_text} ORDER BY issuedat DESC "
                                  f"LIMIT 25 OFFSET ?",
                                  (member.id, ctx.guild.id, (page - 1) * 25)) as cursor:
                now = datetime.now(tz=timezone.utc)
                async for warn in cursor:
                    issuedby = await self.bot.fetch_user(warn[1])
                    issuedat = datetime.fromtimestamp(warn[2], tz=timezone.utc)
                    reason = warn[3]
                    points = warn[5]
                    embed.add_field(name=f"Warn ID #{warn[0]}: {'%g' % points} point{'' if points == 1 else 's'}"
                                         f"{' (Deleted)' if warn[4] else ''}",
                                    value=
                                    f"Reason: {reason}\n"
                                    f"Issued by: {issuedby.mention}\n"
                                    f"Issued {humanize.naturaltime(issuedat, when=now)} "
                                    f"({humanize.naturaldate(issuedat)})")
            async with db.execute("SELECT count(*) FROM warnings WHERE user=? AND server=? AND deactivated=0",
                                  (member.id, ctx.guild.id)) as cur:
                warncount = (await cur.fetchone())[0]
            async with db.execute("SELECT count(*) FROM warnings WHERE user=? AND server=? AND deactivated=1",
                                  (member.id, ctx.guild.id)) as cur:
                delwarncount = (await cur.fetchone())[0]
            async with db.execute("SELECT sum(points) FROM warnings WHERE user=? AND server=? AND deactivated=0",
                                  (member.id, ctx.guild.id)) as cur:
                points = (await cur.fetchone())[0]
                if points is None:
                    points = 0
            embed.description += f" has {'%g' % points} point{'' if warncount == 1 else 's'}, " \
                                 f"{warncount} warn{'' if warncount == 1 else 's'} and " \
                                 f"{delwarncount} deleted warn{'' if delwarncount == 1 else 's'}"
            if not embed.fields:
                embed.add_field(name="No Results", value="Try a different page # or show deleted warns.")
        await ctx.reply(embed=embed)

    @commands.command(aliases=["moderatorlogs", "modlog", "logs"])
    @mod_only()
    async def modlogs(self, ctx, member: discord.User, page: int = 1, viewmodactions: bool = False):
        """
        List a member's warns.

        :Param=member - the member to see the modlogs of.
        :Param=page (optional, default 1) - if the user has more than 25 modlogs, this will let you see pages of modlogs.
        :Param=viewmodactions (optional, default no) - set to yes to view the actions the user took as moderator instead of actions taken against them.
        """
        assert page > 0
        embed = discord.Embed(title=f"Modlogs for {member.display_name}: Page {page}", color=discord.Color(0xB565D9),
                              description=member.mention)
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute(f"SELECT text,datetime,user,moderator FROM modlog "
                                  f"WHERE {'moderator' if viewmodactions else 'user'}=? AND guild=? "
                                  f"ORDER BY datetime DESC LIMIT 25 OFFSET ?",
                                  (member.id, ctx.guild.id, (page - 1) * 25)) as cursor:
                now = datetime.now(tz=timezone.utc)
                async for log in cursor:
                    if log[2]:
                        user: typing.Optional[discord.User] = await self.bot.fetch_user(log[2])
                    else:
                        user = None
                    if log[3]:
                        moderator: typing.Optional[discord.User] = await self.bot.fetch_user(log[3])
                    else:
                        moderator = None
                    issuedat = datetime.fromtimestamp(log[1], tz=timezone.utc)
                    text = log[0]
                    embed.add_field(
                        name=f"{humanize.naturaltime(issuedat, when=now)} ({humanize.naturaldate(issuedat)})",
                        value=
                        text + ("\n\n" if user or moderator else "") +
                        (f"**User**: {user.mention}\n" if user else "") +
                        (f"**Moderator**: {moderator.mention}\n" if moderator else ""))
                if not embed.fields:
                    embed.add_field(name="No Results", value="Try a different page #.")
                await ctx.reply(embed=embed)

    def autopunishment_to_text(self, point_count, point_timespan, punishment_type, punishment_duration):
        punishment_type_future_tense = {
            "ban": "banned",
            "mute": "muted"
        }
        assert punishment_type in punishment_type_future_tense
        timespan_text = "**total**" if point_timespan.total_seconds() == 0 else \
            f"within **{humanize.precisedelta(point_timespan)}**"
        punishment_text = "**permanently**" if punishment_duration.total_seconds() == 0 else \
            f"for **{humanize.precisedelta(punishment_duration)}**"
        return f"When a member receives **{point_count} point{'' if point_count == 1 else 's'}** {timespan_text} they " \
               f"will be {punishment_type_future_tense[punishment_type]} {punishment_text}."

    @commands.command(aliases=["addap", "aap"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def addautopunishment(self, ctx, point_count: int, point_timespan: TimeConverter, punishment_type: str,
                                punishment_duration: TimeConverter):
        """
        Adds an automatic punishment based on the amount of points obtained in a certain time period.

        :Param=point_count - the amount of points that will trigger this punishment. each guild can only have 1 punishment per point count.
        :Param=point_timespan - the timespan that the user must obtain `point_count` point(s) in. specify 0 for no restriction
        :Param=punishment_type - `mute` or `ban`.
        :Param=punishment_duration - the duration the punishment will last. specify 0 for infinite duration.
        """
        assert point_count > 0
        punishment_type = punishment_type.lower()
        ptext = self.autopunishment_to_text(point_count, point_timespan, punishment_type, punishment_duration)
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) added "
                            f"auto-punishment: {ptext}", ctx.guild.id, modid=ctx.author.id)
        await ctx.reply(ptext)
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute(
                "REPLACE INTO auto_punishment(guild,warn_count,punishment_type,punishment_duration,warn_timespan) "
                "VALUES (?,?,?,?,?)",
                (ctx.guild.id, point_count, punishment_type, punishment_duration.total_seconds(),
                 point_timespan.total_seconds()))
            await db.commit()

    @commands.command(aliases=["removeap", "delap", "deleteautopunishment", "rap", "dap"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def removeautopunishment(self, ctx, point_count: int):
        """
        removes an auto-punishment

        :Param=point_count - the point count of the auto-punishment to remove
        """
        assert point_count > 0
        async with aiosqlite.connect("database.sqlite") as db:
            cur = await db.execute("DELETE FROM auto_punishment WHERE warn_count=? AND guild=?",
                                   (point_count, ctx.guild.id))
            await db.commit()
        if cur.rowcount > 0:
            await ctx.reply(f"✔️ Removed rule for {point_count} point{'' if point_count == 1 else 's'}.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"auto-punishment rule for {point_count} "
                                f"point{'' if point_count == 1 else 's'}.", ctx.guild.id, modid=ctx.author.id)
        else:
            await ctx.reply(f"❌ Server has no rule for {point_count} point{'' if point_count == 1 else 's'}!")

    @commands.command(aliases=["listautopunishments", "listap", "ap", "aps"])
    @mod_only()
    async def autopunishments(self, ctx):
        """
        Lists the auto-punishments for the server.
        """
        embed = discord.Embed(title=f"Auto-punishment rules for {ctx.guild.name}", color=discord.Color(0xB565D9))
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT * FROM auto_punishment WHERE guild=? ORDER BY warn_count DESC LIMIT 25",
                                  (ctx.guild.id,)) as cursor:
                async for p in cursor:
                    value = self.autopunishment_to_text(p[1], timedelta(seconds=p[4]), p[2], timedelta(seconds=p[3]))
                    embed.add_field(name=f"Rule for {p[1]} point{'' if p[1] == 1 else 's'}", value=value)
                if not embed.fields:
                    embed.add_field(name="No Auto-punishment Rules", value="This server has no auto-punishments. "
                                                                           "Add some with m.addautopunishment.")
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx, num_messages: int):
        assert num_messages >= 1
        await asyncio.gather(
            ctx.channel.purge(before=ctx.message, limit=num_messages),
            ctx.message.delete(),
            modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) purged {num_messages} message(s) from "
                          f"{ctx.channel.mention}", ctx.guild.id, modid=ctx.author.id)
        )


# @commands.is_owner()
# @commands.command()
# async def delwarn(self, ctx, *warnid: int):
#     async with aiosqlite.connect("database.sqlite") as db:
#         await db.executemany("DELETE FROM warnings WHERE id=?", [(i,) for i in warnid])
#         await db.commit()
#         await ctx.reply("✔️")


# command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
