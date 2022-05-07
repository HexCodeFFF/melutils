import asyncio
import json
import typing
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
import humanize
from discord.ext import commands
from discord.ext.commands import Greedy

import config
import database
import modlog
import scheduler
from clogs import logger
from embedutils import add_long_field, split_embed
from timeconverter import time_converter


async def is_mod(guild: discord.Guild, user: typing.Union[discord.User, discord.Member]):
    if not isinstance(user, discord.Member):
        user = guild.get_member(user.id)
        if user is None:
            return False
    else:
        if user.guild != guild:
            return False
    if user.guild_permissions.manage_guild:
        return True
    modrole = await get_server_config(guild.id, "mod_role")
    if modrole is None:
        return False
    if modrole in [r.id for r in user.roles]:
        return True
    return False


def mod_only():
    async def extended_check(ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        if ctx.author.guild_permissions.manage_guild:
            return True
        modrole = await get_server_config(ctx.guild.id, "mod_role")
        if modrole is None:
            raise commands.CheckFailure("Server has no moderator role set up. Ask an admin to add one.")
        if modrole in [r.id for r in ctx.author.roles]:
            return True
        raise commands.CheckFailure(
            "You need to have the moderator role or Manage Server permissions to run this command.")

    return commands.check(extended_check)


async def update_server_config(server: int, config: str, value):
    """DO NOT ALLOW CONFIG TO BE PASSED AS A VARIABLE, PRE-DEFINED STRINGS ONLY."""
    async with database.db.execute("SELECT COUNT(guild) FROM server_config WHERE guild=?", (server,)) as cur:
        guilds = await cur.fetchone()
    if guilds[0]:  # if there already is a row for this guild
        await database.db.execute(f"UPDATE server_config SET {config} = ? WHERE guild=?", (value, server))
    else:  # if not, make one
        await database.db.execute(f"INSERT INTO server_config(guild, {config}) VALUES (?, ?)", (server, value))
    await database.db.commit()


async def get_server_config(guild: int, config: str):
    """DO NOT ALLOW CONFIG TO BE PASSED AS A VARIABLE, PRE-DEFINED STRINGS ONLY."""
    async with database.db.execute(f"SELECT {config} FROM server_config WHERE guild=?", (guild,)) as cur:
        conf = await cur.fetchone()
    if conf is None:
        return None
    else:
        return conf[0]


async def ban_action(user: typing.Union[discord.User, discord.Member], guild: discord.Guild,
                     ban_length: typing.Optional[timedelta], reason: str):
    async for banned in guild.bans():
        if banned.user.id == user.id:
            return False
    htime = humanize.precisedelta(ban_length)
    if await is_mod(guild, user):
        await modlog.modlog(f"Tried to ban {user.mention} (`{user}`), but they are a mod.", guild.id, user.id)
        return False
    try:
        await guild.ban(user, reason=reason, delete_message_days=0)
        if ban_length is None:
            try:
                await user.send(f"You were permanently banned in **{guild.name}** with reason "
                                f"`{reason}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        else:
            scheduletime = datetime.now(tz=timezone.utc) + ban_length
            await scheduler.schedule(scheduletime, "unban", {"guild": guild.id, "member": user.id})
            try:
                await user.send(f"You were banned in **{guild.name}** for **{htime}** with reason "
                                f"`{reason}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        return True
    except discord.Forbidden:
        await modlog.modlog(f"Tried to ban {user.mention} (`{user}`) "
                            f"but I wasn't able to! Are they an admin?",
                            guild.id, user.id)


def is_timedout(member: discord.Member):
    return member.timed_out_until is not None and member.timed_out_until > datetime.now(tz=timezone.utc)


async def mute_action(member: discord.Member, mute_length: typing.Optional[timedelta], reason: str):
    if is_timedout(member):
        return False
    htime = humanize.precisedelta(mute_length)
    if await is_mod(member.guild, member):
        await modlog.modlog(f"Tried to mute {member.mention} (`{member}`), but they are a mod.",
                            member.guild.id, member.id)
        return False
    if mute_length is None or mute_length > timedelta(days=28):
        # max timeout is 28days
        muteend = (datetime.now(tz=timezone.utc) + mute_length).timestamp() if mute_length else None
        await member.timeout(datetime.now(tz=timezone.utc) + timedelta(days=28), reason=reason)
        await scheduler.schedule(datetime.now(tz=timezone.utc) + timedelta(days=28),
                                 "refresh_mute", {"guild": member.guild.id, "member": member.id, "muteend": muteend})
    else:
        scheduletime = datetime.now(tz=timezone.utc) + mute_length
        await member.timeout(scheduletime, reason=reason)
        # purely cosmetic
        await scheduler.schedule(scheduletime, "unmute", {"guild": member.guild.id, "member": member.id})
    if mute_length is None:
        try:
            await member.send(f"You were permanently muted in **{member.guild.name}** with reason "
                              f"`{reason}`.")
        except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
            logger.debug(e)
    else:

        try:
            await member.send(f"You were muted in **{member.guild.name}** for **{htime}** with reason "
                              f"`{reason}`.")
        except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
            logger.debug(e)
    return True


async def on_warn(member: discord.Member, issued_points: float):
    async with database.db.execute("SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                                   (member.guild.id,)) as cur:
        thin_ice_role = await cur.fetchone()
    if thin_ice_role is not None and thin_ice_role[0] is not None and thin_ice_role[0] in [role.id for role in
                                                                                           member.roles]:
        await database.db.execute(
            "UPDATE thin_ice SET warns_on_thin_ice = warns_on_thin_ice+? WHERE guild=? AND user=?",
            (issued_points, member.guild.id, member.id))
        await database.db.commit()
        threshold = thin_ice_role[1]
        async with database.db.execute("SELECT warns_on_thin_ice FROM thin_ice WHERE guild=? AND user=?",
                                       (member.guild.id, member.id)) as cur:
            warns_on_thin_ice = (await cur.fetchone())[0]
        if warns_on_thin_ice >= threshold:
            await ban_action(member, member.guild, None, f"Automatically banned for receiving more than {threshold}"
                                                         f" points on thin ice.")
            await modlog.modlog(f"{member.mention} (`{member}`) was automatically "
                                f"banned for receiving more than {threshold} "
                                f"points on thin ice.", member.guild.id, member.id)
            await database.db.execute("UPDATE thin_ice SET warns_on_thin_ice = 0 WHERE guild=? AND user=?",
                                      (member.guild.id, member.id))
            await database.db.commit()

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
        async with database.db.execute(monstersql, params) as cur:
            punishment = await cur.fetchone()
        if punishment is not None:
            logger.debug(punishment)
            # punishment_types = {
            #     "ban": ban_action,
            #     "mute": mute_action
            # }
            # func = punishment_types[punishment[2]]
            duration = None if punishment[3] == 0 else timedelta(seconds=punishment[3])
            timespan_text = "total" if punishment[4] == 0 else \
                f"within {humanize.precisedelta(punishment[4])}"
            if punishment[2] == "ban":
                await ban_action(member, member.guild, duration,
                                 f"Automatic punishment due to reaching {punishment[1]} points {timespan_text}")
            elif punishment[2] == "mute":
                await mute_action(member, duration,
                                  f"Automatic punishment due to reaching {punishment[1]} points {timespan_text}")
            punishment_type_future_tense = {
                "ban": "banned",
                "mute": "muted"
            }
            punishment_text = "permanently" if duration.total_seconds() == 0 else \
                f"for {humanize.precisedelta(duration)}"
            await modlog.modlog(
                f"{member.mention} (`{member}`) has been automatically "
                f"{punishment_type_future_tense[punishment[2]]}  {punishment_text} due to reaching {punishment[1]} "
                f"points {timespan_text}", member.guild.id, member.id)


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
                ban_action(message.author, message.guild, None, "Automatically banned for mass ping."),
                modlog.modlog(f"{message.author.mention} (`{message.author}`) "
                              f"was automatically banned for mass ping.", message.guild.id, message.author.id)
            )

    # delete unban events if someone manually unbans with discord.
    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        actuallycancelledanytasks = False
        async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                       "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                       (guild.id, user.id, "unban")) as cur:
            async for row in cur:
                await scheduler.canceltask(row[0])
                actuallycancelledanytasks = True
        thin_ice_role = await get_server_config(guild.id, "thin_ice_role")
        if thin_ice_role is not None:
            await database.db.execute("REPLACE INTO thin_ice(user,guild,marked_for_thin_ice,warns_on_thin_ice) VALUES "
                                      "(?,?,?,?)", (user.id, guild.id, True, 0))
            await database.db.commit()
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
        async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                       "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                       (guild.id, user.id, "un_thin_ice")) as cur:
            async for row in cur:
                await scheduler.canceltask(row[0])
        ban_appeal_link = await get_server_config(guild.id, "ban_appeal_link")
        if ban_appeal_link is not None:
            try:
                await user.send(f"You can appeal your ban from **{guild.name}** at {ban_appeal_link}")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # delete unmute events if someone manually untimed out
        if is_timedout(before) is not None and is_timedout(after) is None:  # if muted role manually removed
            actuallycancelledanytasks = False
            async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                           "AND json_extract(eventdata, \"$.member\")=? AND (eventtype=? OR "
                                           "eventtype=?)",
                                           (after.guild.id, after.id, "unmute", "refresh_mute")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])
                    actuallycancelledanytasks = True
            if actuallycancelledanytasks:
                await after.send(f"You were manually unmuted in **{after.guild.name}**.")
        # remove thin ice from records if manually removed
        thin_ice_role = await get_server_config(after.guild.id, "mod_role")
        if thin_ice_role is not None:
            if thin_ice_role in [role.id for role in before.roles] \
                    and thin_ice_role not in [role.id for role in after.roles]:  # if muted role manually removed
                actuallycancelledanytasks = False
                async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                               "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                               (after.guild.id, after.id, "un_thin_ice")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])
                        await database.db.execute("DELETE FROM thin_ice WHERE guild=? and user=?",
                                                  (after.guild.id, after.id))
                        actuallycancelledanytasks = True
                    await database.db.commit()
                if actuallycancelledanytasks:
                    await after.send(f"Your thin ice was manually removed in **{after.guild.name}**.")
                    await modlog.modlog(f"{after.mention} (`{after}`)'s thin ice was manually removed.",
                                        guildid=after.guild.id, userid=after.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with database.db.execute("SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                                       (member.guild.id,)) as cur:
            thin_ice_role = await cur.fetchone()
        if thin_ice_role is not None and thin_ice_role[0] is not None:
            async with database.db.execute("SELECT * from thin_ice WHERE user=? AND guild=? AND marked_for_thin_ice=1",
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
    async def modrole(self, ctx, *, role: discord.Role = None):
        """
        Sets the server moderator role.
        Anyone who has the mod role can use commands such as mute and warn.

        :param ctx:
        :param role: The moderator role, leave blank to remove the modrole from this server
        """
        if role is None:
            await update_server_config(ctx.guild.id, "mod_role", None)
            await ctx.reply("✔️ Removed server moderator role.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the server mod role.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "mod_role", role.id)
            await ctx.reply(f"✔️ Set server moderator role to **{role.name}**")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"server mod role to {role.mention}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["setthinicerole", "addthinicerole", "setthinice"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def thinicerole(self, ctx, *, role: discord.Role = None):
        """
        Sets the server thin ice role and activates the thin ice system.
        Anyone who has the mod role can use commands such as mute and warn.

        :param ctx: discord context
        :param role: The thin ice role, leave blank to remove the thin ice system from this server
        """
        if role is None:
            await update_server_config(ctx.guild.id, "thin_ice_role", None)
            await ctx.reply("✔️ Removed server thin ice role.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the server mod role.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "thin_ice_role", role.id)
            await ctx.reply(f"✔️ Set server thin ice role to **{role.name}**")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"server thin ice role to {role.mention}", ctx.guild.id, modid=ctx.author.id)

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def thinicethreshold(self, ctx, *, threshold: int = 1):
        """
        Sets the amount of points someone has to get on thin ice to be permanently banned.

        :param ctx: discord context
        :param threshold: - the amount of points someone has to get on thin ice to be permanently banned.
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
    async def logchannel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Sets the server modlog channel.
        All moderator actions will be logged in this channel.

        :param ctx: discord context
        :param channel: - The modlog channel, leave blank to remove the modlog from this server
        """
        if channel is None:
            await update_server_config(ctx.guild.id, "log_channel", None)
            await ctx.reply("✔️ Removed server modlog channel.")
        else:
            await update_server_config(ctx.guild.id, "log_channel", channel.id)
            await ctx.reply(f"✔️ Set server modlog channel to **{channel.mention}**")
            await channel.send(f"This is the new modlog channel for {ctx.guild.name}!")

    @commands.command(aliases=[])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def bulklogchannel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Sets the server "bulk log" channel.
        All server actions will appear in the channel.

        :param ctx: discord context
        :param channel: - The bulk log channel, leave blank to remove the bulk log from this server
        """
        if channel is None:
            await update_server_config(ctx.guild.id, "bulk_log_channel", None)
            await modlog.modlog(f"{ctx.author.mention} ({ctx.author}) removed the server bulklog channel.",
                                ctx.guild.id, ctx.author.id)
            await ctx.reply("✔️ Removed server bulklog channel.")
        else:
            await update_server_config(ctx.guild.id, "bulk_log_channel", channel.id)
            await modlog.modlog(f"{ctx.author.mention} ({ctx.author}) set the server bulklog channel to "
                                f"{channel.mention} ({channel}).", ctx.guild.id, ctx.author.id)
            await ctx.reply(f"✔️ Set server bulklog channel to **{channel.mention}**")

    @commands.command(aliases=["banappeal"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def banappeallink(self, ctx, *, ban_appeal_link=None):
        """
        Sets the server modlog channel.
        All moderator actions will be logged in this channel.

        :param ctx: discord context
        :param ban_appeal_link: - The ban appeal link, leave blank to remove the modlog from this server
        """
        if ban_appeal_link is None:
            await update_server_config(ctx.guild.id, "ban_appeal_link", None)
            await ctx.reply("✔️ Removed server ban appeal link.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the ban appeal link.", ctx.guild.id, modid=ctx.author.id)
        else:
            await update_server_config(ctx.guild.id, "ban_appeal_link", ban_appeal_link)
            await ctx.reply(f"✔️ Set server ban appeal link to **{ban_appeal_link}** .")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"ban appeal link to {ban_appeal_link}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["b", "eat", "vore"])
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def ban(self, ctx, members: Greedy[discord.User],
                  ban_length: typing.Optional[time_converter] = None, *,
                  reason: str = "No reason provided."):
        """
        temporarily or permanently ban one or more members

        :param ctx: discord context
        :param members: one or more members to ban
        :param ban_length: how long to ban them for. don't specify for a permanent ban.
        :param reason: why the user was banned.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        htime = humanize.precisedelta(ban_length)
        for member in members:
            result = await ban_action(member, ctx.guild, ban_length, reason)
            if not result:
                await ctx.reply(f"❌ Failed to ban {member.mention}. Are they already banned or a mod?")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) tried to ban "
                                    f"{member.mention} (`{member}`) for "
                                    f"{f'for **{htime}**' if htime else 'permanently'} with reason "
                                    f"`{reason}`, but it failed. ", ctx.guild.id,
                                    member.id, ctx.author.id)
                continue
            if ban_length is None:
                await ctx.reply(
                    f"✔ Permanently banned **{member.mention}** with reason `{reason}️`")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) banned"
                                    f" {member.mention} (`{member}`) with reason "
                                    f"`{reason}️`", ctx.guild.id, member.id,
                                    ctx.author.id)
            else:
                await ctx.reply(f"✔️ Banned **{member.mention}** for **{htime}** with reason "
                                f"`{reason}`.")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) banned"
                                    f" {member.mention} (`{member}`) for {htime} with reason "
                                    f"`{reason}`.", ctx.guild.id, member.id,
                                    ctx.author.id)

    @commands.command(aliases=["mu"])
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def mute(self, ctx, members: Greedy[discord.Member],
                   mute_length: typing.Optional[time_converter] = None, *,
                   reason: str = "No reason provided."):
        """
        temporarily or permanently mute one or more members

        :param ctx: discord context
        :param members: one or more members to mute
        :param mute_length: how long to mute them for. don't specify for a permanent mute.
        :param reason: why the user was mutes.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        htime = humanize.precisedelta(mute_length)
        for member in members:
            result = await mute_action(member, mute_length, reason)
            if not result:
                await ctx.reply(f"❌ Failed to mute {member.mention}. Are they already banned or a mod?")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) tried to mute "
                                    f"{member.mention} (`{member}`) for "
                                    f"{f'for **{htime}**' if htime else 'permanently'} with reason "
                                    f"`{reason}`, but it failed. ", ctx.guild.id,
                                    member.id, ctx.author.id)
                continue
            if mute_length is None:
                await ctx.reply(
                    f"✔ Permanently muted **{member.mention}** with reason `{reason}️`")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                    f"permanently muted {member.mention} (`{member}`) "
                                    f"with reason "
                                    f"`{reason}️`", ctx.guild.id, member.id,
                                    ctx.author.id)
            else:
                await ctx.reply(f"✔️ Muted **{member.mention}** for **{htime}** with reason "
                                f"`{reason}`.")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) muted "
                                    f"{member.mention} (`{member}`) for **{htime}**"
                                    f" with reason "
                                    f"`{reason}`.", ctx.guild.id, member.id,
                                    ctx.author.id)

    @commands.command(aliases=["um"])
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def unmute(self, ctx, members: Greedy[discord.Member]):
        """
        Unmute one or more members

        :param ctx: discord context
        :param members: one or more members to unmute.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        for member in members:
            # cancel all unmute events
            async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                           "AND json_extract(eventdata, \"$.member\")=? AND (eventtype=? OR eventtype=?)",
                                           (ctx.guild.id, member.id, "unmute", "refresh_mute")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])

            await member.timeout(None)
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

        :param ctx: discord context
        :param members: one or more members to unban.
        """
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        bans = [ban.user for ban in await ctx.guild.bans()]
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
            async with database.db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                           "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                           (ctx.guild.id, member.id, "unban")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])

    @commands.command(aliases=["deletewarn", "removewarn", "dwarn", "cancelwarn", "dw"])
    @mod_only()
    async def delwarn(self, ctx, warn_ids: Greedy[int]):
        """
        Delete a warning.

        :param ctx: discord context
        :param warn_ids: one or more warn IDs to delete. get the ID of a warn with m.warns.
        """
        if not warn_ids:
            await ctx.reply(f"❌ Specify a warn ID.")
        for warn_id in warn_ids:
            async with database.db.execute(
                    "SELECT user, points, reason FROM warnings WHERE id=? AND server=? AND deactivated=0",
                    (warn_id, ctx.guild.id)) as cur:
                warn = await cur.fetchone()
            if warn is None:
                await ctx.reply(
                    f"❌ Failed to remove warning. Does warn #{warn_id} exist and is it from this server?")
            else:
                await database.db.execute("UPDATE warnings SET deactivated=1 WHERE id=?", (warn_id,))
                # update warns on thin ice
                member = await ctx.guild.fetch_member(warn[0])
                points = warn[1]
                async with database.db.execute(
                        "SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                        (member.guild.id,)) as cur:
                    thin_ice_role = await cur.fetchone()
                if thin_ice_role is not None and thin_ice_role[0] is not None \
                        and thin_ice_role[0] in [role.id for role in member.roles]:
                    await database.db.execute(
                        "UPDATE thin_ice SET warns_on_thin_ice = warns_on_thin_ice-? WHERE guild=? AND user=?",
                        (points, member.guild.id, member.id))
                await database.db.commit()
                user = await self.bot.fetch_user(warn[0])
                if user:
                    await ctx.reply(f"✔️ Removed warning #{warn_id} from {user.mention} (`{warn[2]}`)")
                    await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed warning #{warn_id} from "
                                        f"{user.mention} ({user}). Warn text was `{warn[2]}`", ctx.guild.id,
                                        modid=ctx.author.id, userid=user.id)
                    try:
                        await user.send(f"A warn you received in {ctx.guild.name} for was deleted. "
                                        f"(`{warn[2]}`)")
                    except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
                        logger.debug("pass;" + str(e))
                else:
                    await ctx.reply(f"✔️ Removed warning #{warn_id} from <@{warn[0]}> (`{warn[2]}`)")
                    await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed warning #{warn_id} from "
                                        f"{user.mention}. Warn text was `{warn[2]}`", ctx.guild.id,
                                        modid=ctx.author.id, userid=user.id)

    @commands.command(aliases=["restorewarn", "undeletewarn", "udw"])
    @mod_only()
    async def undelwarn(self, ctx, warn_id: int):
        """
        Undelete a warning.

        :param ctx: discord context
        :param warn_id: a warn ID to restore. get the ID of a warn with m.warns.
        """
        async with database.db.execute(
                "SELECT user, points, reason FROM warnings WHERE id=? AND server=? AND deactivated=0",
                (warn_id, ctx.guild.id)) as cur:
            warn = await cur.fetchone()
        if warn is None:
            await ctx.reply(
                f"❌ Failed to unremove warning. Does warn #{warn_id} exist and is it from this server?")
        else:
            await database.db.execute("UPDATE warnings SET deactivated=1 WHERE id=?", (warn_id,))
            await database.db.commit()
            user = await self.bot.fetch_user(warn[0])
            if user:
                await ctx.reply(f"✔️ Restored warning #{warn_id} from {user.mention} (`{warn[2]}`)")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) restored warning #{warn_id} from "
                                    f"{user.mention} ({user}). Warn text was `{warn[2]}`", ctx.guild.id,
                                    modid=ctx.author.id, userid=user.id)
                try:
                    await user.send(f"A previously deleted warn you received in {ctx.guild.name} was restored. "
                                    f"(`{warn[2]}`)")
                except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
                    logger.debug("pass;" + str(e))
            else:
                await ctx.reply(f"✔️ Removed warning #{warn_id} from <@{warn[0]}> (`{warn[2]}`)")
                await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed warning #{warn_id} from "
                                    f"{user.mention}. Warn text was `{warn[2]}`", ctx.guild.id,
                                    modid=ctx.author.id, userid=user.id)

    @commands.command(aliases=["w", "bite"])
    @mod_only()
    async def warn(self, ctx, members: Greedy[discord.Member], points: typing.Optional[float] = 1, *,
                   reason="No reason provided."):
        """
        Warn a member.

        :param ctx: discord context
        :param members: the member(s) to warn.
        :param points: the amount of points this warn is worth. think of it as a warn weight.
        :param reason: the reason for warning the member.
        """
        assert points >= 0
        if points > 1:
            points = round(points, 1)
        now = datetime.now(tz=timezone.utc)
        for member in members:
            async with database.db.cursor() as cur:
                cur: aiosqlite.Cursor
                await cur.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                                  "VALUES (?, ?, ?, ?, ?, ?)",
                                  (ctx.guild.id, member.id, ctx.author.id,
                                   int(now.timestamp()), reason, points))
                insertedrow = cur.lastrowid
            await database.db.commit()

            await ctx.reply(
                f"Warned {member.mention} (warn ID `#{insertedrow}`) with {points} infraction point{'' if points == 1 else 's'} for: "
                f"`{reason}`")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                f"warned {member.mention} (`{member}`) (warn ID `#{insertedrow}`) with {points}"
                                f" infraction point{'' if points == 1 else 's'} for: "
                                f"`{reason}`", ctx.guild.id, member.id, ctx.author.id)
            try:
                await member.send(f"You were warned in {ctx.guild.name} for `{reason}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError) as e:
                logger.debug("pass;" + str(e))
            await on_warn(member, points)  # this handles autopunishments

    @commands.command(aliases=["n", "modnote"])
    @mod_only()
    async def note(self, ctx, member: discord.User, *, n: str):
        """
        Creates a note for a user which shows up in the user's modlogs.

        :param ctx: discord context
        :param member: the member to make a note for
        :param n: the note to make for the member
        """

        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                            f"created a note for {member.mention} (`{member}`): "
                            f"`{n}`", ctx.guild.id, member.id, ctx.author.id)
        await ctx.reply(f"✅ Created note for {member.mention}")

    @commands.command(aliases=["ow", "transferwarn"])
    @mod_only()
    async def oldwarn(self, ctx, member: discord.Member, day: int, month: int, year: int,
                      points: typing.Optional[float] = 1, *, reason="No reason provided."):
        """
        Creates a warn for a member issued at a custom date. Useful for transferring old warns.

        :param ctx: discord context
        :param member: the member to warn
        :param day: day of the warn
        :param month: month of the warn
        :param year: year of the warn
        :param points: the amount of points this warn is worth. think of it as a warn weight.
        :param reason: the reason for warning the member.
        """
        assert points > 0
        if points > 1:
            points = round(points, 1)
        now = datetime(day=day, month=month, year=year, tzinfo=timezone.utc)
        await database.db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                                  "VALUES (?, ?, ?, ?, ?, ?)",
                                  (ctx.guild.id, member.id, ctx.author.id,
                                   int(now.timestamp()), reason, points))
        await database.db.commit()
        await ctx.reply(
            f"Created warn on <t:{int(now.timestamp())}:D> for {member.mention} with {points} infraction "
            f"point{'' if points == 1 else 's'} for: `{reason}`")
        await modlog.modlog(
            f"{ctx.author.mention} (`{ctx.author}`) created warn on "
            f"<t:{int(now.timestamp())}:D> for {member.mention} (`{member}`) with"
            f" {points} "
            f"infraction point{'' if points == 1 else 's'} for: "
            f"`{reason}`", ctx.guild.id, member.id, ctx.author.id)
        # try:
        #     await member.send(f"You were warned in {ctx.guild.name} for `{reason}`.")
        # except (discord.Forbidden, discord.HTTPException, AttributeError):
        #     logger.debug("pass")
        await on_warn(member, points)  # this handles autopunishments

    @commands.command(aliases=["warnings", "listwarns", "listwarn", "ws"])
    @mod_only()
    async def warns(self, ctx, member: discord.User, page: int = 1, show_deleted: bool = False):
        """
        List a member's warns.

        :param ctx: discord context
        :param member: the member to see the warns of.
        :param page: if the user has more than 25 warns, this will let you see pages of warns.
        :param show_deleted: show deleted warns.
        :returns: list of warns
        """
        assert page > 0
        async with ctx.channel.typing():
            embed = discord.Embed(title=f"Warns for {member.display_name}: Page {page}", color=discord.Color(0xB565D9),
                                  description=member.mention)
            deactivated_text = "" if show_deleted else "AND deactivated=0"
            async with database.db.execute(f"SELECT id, issuedby, issuedat, reason, deactivated, points FROM warnings "
                                           f"WHERE user=? AND server=? {deactivated_text} ORDER BY issuedat DESC "
                                           f"LIMIT 25 OFFSET ?",
                                           (member.id, ctx.guild.id, (page - 1) * 25)) as cursor:
                # now = datetime.now(tz=timezone.utc)
                async for warn in cursor:
                    issuedby = await self.bot.fetch_user(warn[1])
                    issuedat = warn[2]
                    reason = warn[3]
                    points = warn[5]
                    add_long_field(embed,
                                   name=f"Warn ID `#{warn[0]}`: {'%g' % points} point{'' if points == 1 else 's'}"
                                        f"{' (Deleted)' if warn[4] else ''}",
                                   value=
                                   f"Reason: {reason}\n"
                                   f"Issued by: {issuedby.mention}\n"
                                   f"Issued <t:{int(issuedat)}:f> "
                                   f"(<t:{int(issuedat)}:R>)", inline=False)
            async with database.db.execute("SELECT count(*) FROM warnings WHERE user=? AND server=? AND deactivated=0",
                                           (member.id, ctx.guild.id)) as cur:
                warncount = (await cur.fetchone())[0]
            async with database.db.execute("SELECT count(*) FROM warnings WHERE user=? AND server=? AND deactivated=1",
                                           (member.id, ctx.guild.id)) as cur:
                delwarncount = (await cur.fetchone())[0]
            async with database.db.execute(
                    "SELECT sum(points) FROM warnings WHERE user=? AND server=? AND deactivated=0",
                    (member.id, ctx.guild.id)) as cur:
                points = (await cur.fetchone())[0]
                if points is None:
                    points = 0
            embed.description += f" has {'%g' % points} point{'' if points == 1 else 's'}, " \
                                 f"{warncount} warn{'' if warncount == 1 else 's'} and " \
                                 f"{delwarncount} deleted warn{'' if delwarncount == 1 else 's'}"
            if not embed.fields:
                embed.add_field(name="No Results", value="Try a different page # or show deleted warns.",
                                inline=False)
            for e in split_embed(embed):
                await ctx.reply(embed=e)

    @commands.command(aliases=["moderatorlogs", "modlog", "logs"])
    @mod_only()
    async def modlogs(self, ctx, member: discord.User, page: int = 1, viewmodactions: bool = False):
        """
        List moderator actions taken against a member.

        :param ctx: discord context
        :param member: the member to see the modlogs of.
        :param page: if the user has more than 10 modlogs, this will let you see pages of modlogs.
        :param viewmodactions: set to yes to view the actions the user took as moderator instead of actions taken
        against them.
        :returns: list of actions taken against them
        """
        assert page > 0
        async with ctx.channel.typing():
            embed = discord.Embed(title=f"Modlogs for {member.display_name}: Page {page}",
                                  color=discord.Color(0xB565D9), description=member.mention)
            async with database.db.execute(f"SELECT text,datetime,user,moderator FROM modlog "
                                           f"WHERE {'moderator' if viewmodactions else 'user'}=? AND guild=? "
                                           f"ORDER BY datetime DESC LIMIT 10 OFFSET ?",
                                           (member.id, ctx.guild.id, (page - 1) * 10)) as cursor:
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
                    issuedat = log[1]
                    text = log[0]
                    add_long_field(embed,
                                   name=f"<t:{int(issuedat)}:f> (<t:{int(issuedat)}:R>)",
                                   value=
                                   text + ("\n\n" if user or moderator else "") +
                                   (f"**User**: {user.mention}\n" if user else "") +
                                   (f"**Moderator**: {moderator.mention}\n" if moderator else ""), inline=False)
                if not embed.fields:
                    embed.add_field(name="No Results", value="Try a different page #.", inline=False)
                for e in split_embed(embed):
                    await ctx.reply(embed=e)

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
    async def addautopunishment(self, ctx, point_count: int, point_timespan: time_converter, punishment_type: str,
                                punishment_duration: time_converter):
        """
        Adds an automatic punishment based on the amount of points obtained in a certain time period.

        :param ctx: discord context
        :param point_count: the amount of points that will trigger this punishment. each guild can only have 1
        punishment per point count and timespan.
        :param point_timespan: the timespan that the user must obtain `point_count` point(s) in. specify 0 for no
        restriction
        :param punishment_type: `mute` or `ban`.
        :param punishment_duration: the duration the punishment will last. specify 0 for infinite duration.
        """
        assert point_count > 0
        punishment_type = punishment_type.lower()
        ptext = self.autopunishment_to_text(point_count, point_timespan, punishment_type, punishment_duration)
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) added "
                            f"auto-punishment: {ptext}", ctx.guild.id, modid=ctx.author.id)
        await ctx.reply(ptext)
        await database.db.execute(
            "REPLACE INTO auto_punishment(guild,warn_count,punishment_type,punishment_duration,warn_timespan) "
            "VALUES (?,?,?,?,?)",
            (ctx.guild.id, point_count, punishment_type, punishment_duration.total_seconds(),
             point_timespan.total_seconds()))
        await database.db.commit()

    @commands.command(aliases=["removeap", "delap", "deleteautopunishment", "rap", "dap"])
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def removeautopunishment(self, ctx, point_count: int):
        """
        removes an auto-punishment

        :param ctx: discord context
        :param point_count: the point count of the auto-punishment to remove
        """
        assert point_count > 0
        cur = await database.db.execute("DELETE FROM auto_punishment WHERE warn_count=? AND guild=?",
                                        (point_count, ctx.guild.id))
        await database.db.commit()
        if cur.rowcount > 0:
            await ctx.reply(f"✔️ Removed rule for {point_count} point{'' if point_count == 1 else 's'}.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"auto-punishment rule for {point_count} "
                                f"point{'' if point_count == 1 else 's'}.", ctx.guild.id, modid=ctx.author.id)
        else:
            await ctx.reply(f"❌ Server has no rule for {point_count} point{'' if point_count == 1 else 's'}!")

    @commands.command(aliases=["listautopunishments", "listap", "aps"])
    @mod_only()
    async def autopunishments(self, ctx):
        """
        Lists the auto-punishments for the server.
        """
        embed = discord.Embed(title=f"Auto-punishment rules for {ctx.guild.name}", color=discord.Color(0xB565D9))
        async with database.db.execute("SELECT * FROM auto_punishment WHERE guild=? ORDER BY warn_count DESC LIMIT 25",
                                       (ctx.guild.id,)) as cursor:
            async for p in cursor:
                value = self.autopunishment_to_text(p[1], timedelta(seconds=p[4]), p[2], timedelta(seconds=p[3]))
                embed.add_field(name=f"Rule for {p[1]} point{'' if p[1] == 1 else 's'}", value=value, inline=False)
            if not embed.fields:
                embed.add_field(name="No Auto-punishment Rules", value="This server has no auto-punishments. "
                                                                       "Add some with m.addautopunishment.",
                                inline=False)
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx: commands.Context, num_messages: int, clean: bool = True):
        """
        bulk delete messages from a channel

        :param ctx: discord context
        :param num_messages: number of messages before command invocation to delete
        """
        assert num_messages >= 1
        deleted = await ctx.channel.purge(before=ctx.message, limit=num_messages)
        msg = f"{config.emojis['check']} Deleted `{len(deleted)}` message{'' if len(deleted) == 1 else 's'}!"
        if clean:
            await ctx.send(msg, delete_after=10)
        else:
            await ctx.reply(msg)
        await ctx.message.delete()
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) purged {len(deleted)} message(s) from "
                            f"{ctx.channel.mention}", ctx.guild.id, modid=ctx.author.id)

    @mod_only()
    @commands.command(aliases=["unlock", "unlockchannel", "lockch", "lockc", "lchannel"])
    async def lockchannel(self, ctx: commands.Context,
                          channel: typing.Optional[discord.TextChannel] = None,
                          allow_mods_to_speak: bool = True):
        """
        lock or unlock a channel
        :param ctx:
        :param channel: optionally specify a channel other than the current channel to lock
        :param allow_mods_to_speak: allow mods to speak in the locked channel
        """
        if channel is None:
            if isinstance(ctx.channel, discord.TextChannel):
                channel = ctx.channel
            else:
                raise commands.BadArgument("Channel must be a text channel")
        assert channel.guild == ctx.guild, "Channel must be in this server!"
        async with ctx.channel.typing():
            async with database.db.execute("SELECT data FROM lockedchannelperms WHERE guild=? AND channel=?",
                                           (channel.guild.id, channel.id)) as cur:
                row = await cur.fetchone()
            if row is None:  # unlocked, need to lock
                # store current perms in database
                perms = {}
                for role, ovr in channel.overwrites.items():
                    allow, deny = ovr.pair()
                    perms[role.id] = {'allow': allow.value, 'deny': deny.value}
                perms = json.dumps(perms)
                logger.debug(perms)
                await database.db.execute("INSERT INTO lockedchannelperms VALUES (?,?,?)",
                                          (channel.guild.id, channel.id, perms))
                await database.db.commit()
                # update perms
                modrole = ctx.guild.get_role(int(await get_server_config(ctx.guild.id, "mod_role")))
                for target, ovr in channel.overwrites.items():
                    # dont fuck with perms above mods
                    if isinstance(target, discord.Role) and target >= modrole:
                        continue
                    ovr.update(send_messages=False, send_messages_in_threads=False, create_private_threads=False,
                               create_public_threads=False)
                    await channel.set_permissions(target, overwrite=ovr, reason="Channel lock")
                if not allow_mods_to_speak:
                    modovrs = channel.overwrites_for(modrole)
                    modovrs.update(send_messages=False, send_messages_in_threads=False, create_private_threads=False,
                                   create_public_threads=False)
                    await channel.set_permissions(target, overwrite=modovrs, reason="Channel lock")
                # reply!
                await modlog.modlog(f"{ctx.author.mention} (`@{ctx.author}`) locked {channel.mention} (`#{channel}`)",
                                    ctx.guild.id, modid=ctx.author.id)
                await ctx.reply(f"✔ Locked channel")
            else:  # locked, need to unlock
                data = json.loads(row[0])
                logger.debug(data)
                # delete any excess perms
                for target, override in channel.overwrites.items():
                    if target.id in [int(kid) for kid in data.keys()]:
                        try:
                            await channel.set_permissions(target, overwrite=None, reason="Channel unlock")
                        except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                            logger.debug(e)
                # restore original permissions
                for k, v in data.items():
                    if (target := channel.guild.get_role(int(k))) is None:
                        if (target := channel.guild.get_member(int(k))) is None:
                            continue
                    overwrite = discord.PermissionOverwrite.from_pair(discord.Permissions(v['allow']),
                                                                      discord.Permissions(v['deny']))
                    try:
                        await channel.set_permissions(target, overwrite=overwrite, reason="Channel unlock")
                    except (discord.Forbidden, discord.HTTPException, discord.NotFound) as e:
                        logger.debug(e)
                # update db
                await database.db.execute("DELETE FROM lockedchannelperms WHERE guild=? AND channel=?",
                                          (channel.guild.id, channel.id))
                await database.db.commit()
                # reply!
                await modlog.modlog(f"{ctx.author.mention} (`@{ctx.author}`) unlocked {channel.mention} (`#{channel}`)",
                                    ctx.guild.id, modid=ctx.author.id)
                await ctx.reply(f"✔ Unlocked channel")

    @mod_only()
    @commands.command()
    async def lock(self, ctx: commands.Context,
                   channel: typing.Optional[typing.Union[discord.TextChannel, discord.Thread]] = None):
        """
        shortcut command for locking text channels or threads
        performs m.lockthread on threads and m.lockchannel on channels
        :param ctx:
        :param channel: text channel or thread to lock other than the current one.
        """
        if channel is None:
            channel = ctx.channel
        if isinstance(channel, discord.TextChannel):
            cmd: commands.Command = self.bot.get_command("lockchannel")
        else:
            cmd: commands.Command = self.bot.get_command("lockthread")
        if await cmd.can_run(ctx):
            await cmd.__call__(ctx, channel)
        else:
            await ctx.reply(f"❌ Failed to lock channel.")


# @commands.is_owner()


# command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
