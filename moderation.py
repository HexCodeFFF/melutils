import asyncio
import copy
import re
import typing
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
import humanize
from discord.ext import commands
from discord.ext.commands import Greedy

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
    """DO NOT ALLOW CONFIG TO BE PASSED AS A VARIABLE, PRE-DEFINED STRINGS ONLY."""
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
        *[channel.set_permissions(muted_role, send_messages=False, speak=False, add_reactions=False,
                                  reason='Setting up mute system.')
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


async def ban_action(user: typing.Union[discord.User, discord.Member], guild: discord.Guild,
                     ban_length: typing.Optional[timedelta], reason: str):
    bans = [ban.user for ban in await guild.bans()]
    if user in bans:
        return False
    htime = humanize.precisedelta(ban_length)
    try:
        await guild.ban(user, reason=reason, delete_message_days=0)
        if ban_length is None:
            try:
                await user.send(f"You were permanently banned in **{guild.name}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        else:
            scheduletime = datetime.now(tz=timezone.utc) + ban_length
            await scheduler.schedule(scheduletime, "unban", {"guild": guild.id, "member": user.id})
            try:
                await user.send(f"You were banned in **{guild.name}** for **{htime}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")
        return True
    except discord.Forbidden:
        await modlog.modlog(f"Tried to ban {user.mention} (`{user}`) "
                            f"but I wasn't able to! Are they an admin?",
                            guild.id, user.id)


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
                await ban_action(member, member.guild, None, f"Automatically banned for receiving more than {threshold}"
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
                    f"{member.mention} (`{member}`) has been automatically {punishment_type_future_tense[punishment[2]]}"
                    f" {punishment_text} due to reaching {punishment[1]} points {timespan_text}",
                    member.guild.id, member.id)


def add_long_field(embed: discord.Embed, name: str, value: str, inline: bool = False,
                   erroriftoolong: bool = False) -> discord.Embed:
    """
    add fields every 1024 characters to a discord embed
    :param inline: inline of embed
    :param embed: embed
    :param name: title of embed
    :param value: long value
    :param erroriftoolong: if true, throws an error if embed exceeds 6000 in length
    :return: updated embed
    """
    if len(value) <= 1024:
        return embed.add_field(name=name, value=value, inline=inline)
    else:
        for i, section in enumerate(re.finditer('.{1,1024}', value, flags=re.S)):  # split every 1024 chars
            embed.add_field(name=name + f" {i + 1}", value=section[0], inline=inline)
    if len(embed) > 6000 and erroriftoolong:
        raise Exception(f"Generated embed exceeds maximum size. ({len(embed)} > 6000)")
    return embed


def split_embed(embed: discord.Embed) -> typing.List[discord.Embed]:
    """
    splits one embed into one or more embeds to avoid hitting the 6000 char limit
    :param embed: the initial embed
    :return: a list of embeds, none of which should have more than 25 fields or more than 6000 chars
    """
    out = []
    baseembed = copy.deepcopy(embed)
    baseembed.clear_fields()
    if len(baseembed) > 6000:
        raise Exception(f"Embed without fields exceeds 6000 chars.")
    currentembed = copy.deepcopy(baseembed)
    for field in embed.fields:  # for every field in the embed
        currentembed.add_field(name=field.name, value=field.value,
                               inline=field.inline)  # add it to the "currentembed" object we are working on
        if len(currentembed) > 6000 or len(currentembed.fields) > 25:  # if the currentembed object is too big
            currentembed.remove_field(-1)  # remove the field
            out.append(currentembed)  # add the embed to our output
            currentembed = copy.deepcopy(baseembed)  # make a new embed
            currentembed.add_field(name=field.name, value=field.value,
                                   inline=field.inline)  # add the field to our new embed instead
    out.append(currentembed)  # add the final embed which didnt exceed 6000 to the output
    return out


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
                    await scheduler.canceltask(row[0], db)
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

        # TEMPORARY SHIT TODO: DELETE
        if guild.id == 829973626442088468 and not actuallycancelledanytasks and datetime.now(
                tz=timezone.utc).timestamp() < 1637366400:
            await ban_action(user, guild, None,
                             reason="Due to threats of a raid, all permanent unbans are disabled for now.")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                  "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                  (guild.id, user.id, "un_thin_ice")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0], db)
            async with db.execute("SELECT ban_appeal_link FROM server_config WHERE guild=?", (guild.id,)) as cur:
                ban_appeal_link = await cur.fetchone()
        if ban_appeal_link is not None and ban_appeal_link[0] is not None:
            try:
                await user.send(f"You can appeal your ban from **{guild.name}** at {ban_appeal_link[0]}")
            except (discord.Forbidden, discord.HTTPException, AttributeError):
                logger.debug("pass")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # delete unmute events if someone removed the role manually with discord
        muted_role = await get_muted_role(after.guild)
        if muted_role in before.roles and muted_role not in after.roles:  # if muted role manually removed
            actuallycancelledanytasks = False
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (after.guild.id, after.id, "unmute")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0], db)
                        actuallycancelledanytasks = True
            if actuallycancelledanytasks:
                await after.send(f"You were manually unmuted in **{after.guild.name}**.")
        # remove thin ice from records if manually removed
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT thin_ice_role FROM server_config WHERE guild=?",
                                  (after.guild.id,)) as cur:
                thin_ice_role = await cur.fetchone()
            if thin_ice_role is not None and thin_ice_role[0] is not None:
                if thin_ice_role[0] in [role.id for role in before.roles] \
                        and thin_ice_role[0] not in [role.id for role in after.roles]:  # if muted role manually removed
                    actuallycancelledanytasks = False
                    async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                          "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                          (after.guild.id, after.id, "un_thin_ice")) as cur:
                        async for row in cur:
                            await scheduler.canceltask(row[0], db)
                            await db.execute("DELETE FROM thin_ice WHERE guild=? and user=?",
                                             (after.guild.id, after.id))
                            actuallycancelledanytasks = True
                        await db.commit()
                    if actuallycancelledanytasks:
                        await after.send(f"Your thin ice was manually removed in **{after.guild.name}**.")
                        await modlog.modlog(f"{after.mention} (`{after}`)'s thin ice was manually removed.",
                                            guildid=after.guild.id, userid=after.id)

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
            await ctx.reply(f"✔️ Set server thin ice role to **{discord.utils.escape_mentions(role.name)}**")
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
    async def logchannel(self, ctx, *, channel: typing.Optional[discord.TextChannel] = None):
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
            await ctx.reply(f"✔️ Set server modlog channel to **{discord.utils.escape_mentions(channel.mention)}**")
            await channel.send(f"This is the new modlog channel for {ctx.guild.name}!")

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
            await ctx.reply(f"✔️ Set server ban appeal link to **{discord.utils.escape_mentions(ban_appeal_link)}** .")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"ban appeal link to {ban_appeal_link}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["b", "eat", "vore"])
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def ban(self, ctx, members: Greedy[discord.User],
                  ban_length: typing.Optional[TimeConverter] = None, *,
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

        :param ctx: discord context
        :param members: one or more members to unmute.
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
                        await scheduler.canceltask(row[0], db)
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

        :param ctx: discord context
        :param members: one or more members to unban.
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
                        await scheduler.canceltask(row[0], db)

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
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT user, points FROM warnings WHERE id=? AND server=? AND deactivated=0",
                                      (warn_id, ctx.guild.id)) as cur:
                    warn = await cur.fetchone()
                if warn is None:
                    await ctx.reply(
                        f"❌ Failed to remove warning. Does warn #{warn_id} exist and is it from this server?")
                else:
                    cur = await db.execute("UPDATE warnings SET deactivated=1 WHERE id=?", (warn_id,))
                    # update warns on thin ice
                    member = await ctx.guild.fetch_member(warn[0])
                    points = warn[1]
                    async with db.execute("SELECT thin_ice_role, thin_ice_threshold FROM server_config WHERE guild=?",
                                          (member.guild.id,)) as cur:
                        thin_ice_role = await cur.fetchone()
                    if thin_ice_role is not None and thin_ice_role[0] is not None \
                            and thin_ice_role[0] in [role.id for role in member.roles]:
                        await db.execute(
                            "UPDATE thin_ice SET warns_on_thin_ice = warns_on_thin_ice-? WHERE guild=? AND user=?",
                            (points, member.guild.id, member.id))
                    await db.commit()
                    await ctx.reply(f"✔️ Removed warning #{warn_id}")
                    await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) "
                                        f"removed warning #{warn_id}", ctx.guild.id, modid=ctx.author.id)

    @commands.command(aliases=["restorewarn", "undeletewarn", "udw"])
    @mod_only()
    async def undelwarn(self, ctx, warn_id: int):
        """
        Undelete a warning.

        :param ctx: discord context
        :param warn_id: a warn ID to restore. get the ID of a warn with m.warns.
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
                            f"`{discord.utils.escape_mentions(n)}`", ctx.guild.id, member.id, ctx.author.id)
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
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, member.id, ctx.author.id,
                              int(now.timestamp()), reason, points))
            await db.commit()
        await ctx.reply(
            f"Created warn on <t:{int(now.timestamp())}:D> for {member.mention} with {points} infraction "
            f"point{'' if points == 1 else 's'} for: `{discord.utils.escape_mentions(reason)}`")
        await modlog.modlog(
            f"{ctx.author.mention} (`{ctx.author}`) created warn on "
            f"<t:{int(now.timestamp())}:D> for {member.mention} (`{member}`) with"
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
            async with aiosqlite.connect("database.sqlite") as db:
                deactivated_text = "" if show_deleted else "AND deactivated=0"
                async with db.execute(f"SELECT id, issuedby, issuedat, reason, deactivated, points FROM warnings "
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
                                       name=f"Warn ID #{warn[0]}: {'%g' % points} point{'' if points == 1 else 's'}"
                                            f"{' (Deleted)' if warn[4] else ''}",
                                       value=
                                       f"Reason: {reason}\n"
                                       f"Issued by: {issuedby.mention}\n"
                                       f"Issued <t:{int(issuedat)}:f> "
                                       f"(<t:{int(issuedat)}:R>)", inline=False)
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
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute(f"SELECT text,datetime,user,moderator FROM modlog "
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
    async def addautopunishment(self, ctx, point_count: int, point_timespan: TimeConverter, punishment_type: str,
                                punishment_duration: TimeConverter):
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

        :param ctx: discord context
        :param point_count: the point count of the auto-punishment to remove
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
                    embed.add_field(name=f"Rule for {p[1]} point{'' if p[1] == 1 else 's'}", value=value, inline=False)
                if not embed.fields:
                    embed.add_field(name="No Auto-punishment Rules", value="This server has no auto-punishments. "
                                                                           "Add some with m.addautopunishment.",
                                    inline=False)
        await ctx.reply(embed=embed)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx, num_messages: int):
        """
        bulk delete messages from a channel

        :param ctx: discord context
        :param num_messages: number of messages before command invocation to delete
        """
        assert num_messages >= 1
        await asyncio.gather(
            ctx.channel.purge(before=ctx.message, limit=num_messages),
            ctx.message.delete(),
            modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) purged {num_messages} message(s) from "
                          f"{ctx.channel.mention}", ctx.guild.id, modid=ctx.author.id)
        )


# @commands.is_owner()


# command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
