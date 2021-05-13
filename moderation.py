import asyncio
from numbers import Number

import aiosqlite
import discord
from discord.ext import commands
import typing

from discord.ext.commands import Greedy

import scheduler
from timeconverter import TimeConverter
import time
from datetime import datetime, timezone, timedelta
import humanize
from clogs import logger


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
    logger.debug("SETTING UP MUTED ROLE")
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


async def on_warn(member: discord.Member):
    pass


async def get_muted_role(guild: discord.Guild) -> discord.Role:
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (guild.id,)) as cur:
            mutedrole = await cur.fetchone()
    if mutedrole is None or mutedrole[0] is None:
        muted_role = await set_up_muted_role(guild)
    else:
        muted_role = guild.get_role(mutedrole[0])
    return muted_role


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild:
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT muted_role FROM server_config WHERE guild=?", (message.guild.id,)) as cur:
                    mutedrole = await cur.fetchone()
            if mutedrole is not None and mutedrole[0] is not None:
                if mutedrole[0] in [role.id for role in message.author.roles]:
                    await message.delete(reason="User is muted.")

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
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                  "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                  (guild.id, user.id, "unban")) as cur:
                async for row in cur:
                    await scheduler.canceltask(row[0])

    # delete unmute events if someone removed the role manually with discord
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        muted_role = await get_muted_role(after.guild)
        if muted_role in before.roles and muted_role not in after.roles:  # if muted role manually removed
            async with aiosqlite.connect("database.sqlite") as db:
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (after.guild.id, after.id, "unmute")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])

    @commands.command(aliases=["setmodrole", "addmodrole", "moderatorrole"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def modrole(self, ctx, *, role: typing.Union[discord.Role, None] = None):
        if role is None:
            await update_server_config(ctx.guild.id, "mod_role", None)
            await ctx.reply("✔️ Removed server moderator role.")
        else:
            await update_server_config(ctx.guild.id, "mod_role", role.id)
            await ctx.reply(f"✔️ Set server moderator role to **{discord.utils.escape_mentions(role.name)}**")

    @commands.command(aliases=["setlogchannel", "modlogchannel", "moderatorlogchannel", "setmodlogchannel"])
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def logchannel(self, ctx, *, ch: typing.Union[discord.TextChannel, None] = None):
        if ch is None:
            await update_server_config(ctx.guild.id, "log_channel", None)
            await ctx.reply("✔️ Removed server modlog channel.")
        else:
            await update_server_config(ctx.guild.id, "log_channel", ch.id)
            await ctx.reply(f"✔️ Set server modlog channel to **{discord.utils.escape_mentions(ch.mention)}**")

    @commands.command()
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def ban(self, ctx, members: Greedy[discord.User],
                  ban_length: typing.Optional[typing.Union[TimeConverter, None]] = None, *,
                  reason: str = "No reason provided."):
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        htime = humanize.precisedelta(ban_length)
        bans = [ban.user for ban in await ctx.guild.bans()]
        for member in members:
            if member in bans:
                await ctx.reply(f"❌ {member.mention} is already banned!")
                continue
            await ctx.guild.ban(member, reason=reason)
            if ban_length is None:
                await ctx.reply(
                    f"✔ Permanently banned **{member.mention}** with reason `{discord.utils.escape_mentions(reason)}️`")
                try:
                    await member.send(f"You were permanently banned in **{ctx.guild.name}** with reason "
                                      f"`{discord.utils.escape_mentions(reason)}`.")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            else:
                scheduletime = datetime.now(tz=timezone.utc) + ban_length
                await scheduler.schedule(scheduletime, "unban", {"guild": ctx.guild.id, "member": member.id})
                await ctx.reply(f"✔️ Banned **{member.mention}** for **{htime}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
                try:
                    await member.send(f"You were banned in **{ctx.guild.name}** for **{htime}** with reason "
                                      f"`{discord.utils.escape_mentions(reason)}`.")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.command()
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def mute(self, ctx, members: Greedy[discord.Member],
                   mute_length: typing.Optional[typing.Union[TimeConverter, None]] = None, *,
                   reason: str = "No reason provided."):
        if not members:
            await ctx.reply("❌ members is a required argument that is missing.")
            return
        muted_role = await get_muted_role(ctx.guild)
        htime = humanize.precisedelta(mute_length)
        for member in members:
            if muted_role in member.roles:
                await ctx.reply(f"❌ {member.mention} is already muted!")
                continue
            await member.add_roles(muted_role, reason=reason)
            if mute_length is None:
                await ctx.reply(
                    f"✔ Permanently muted **{member.mention}** with reason `{discord.utils.escape_mentions(reason)}️`")
                try:
                    await member.send(f"You were permanently muted in **{ctx.guild.name}** with reason "
                                      f"`{discord.utils.escape_mentions(reason)}`.")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            else:
                scheduletime = datetime.now(tz=timezone.utc) + mute_length
                await scheduler.schedule(scheduletime, "unmute",
                                         {"guild": ctx.guild.id, "member": member.id, "mute_role": muted_role.id})
                await ctx.reply(f"✔️ Muted **{member.mention}** for **{htime}** with reason "
                                f"`{discord.utils.escape_mentions(reason)}`.")
                try:
                    await member.send(f"You were muted in **{ctx.guild.name}** for **{htime}** with reason "
                                      f"`{discord.utils.escape_mentions(reason)}`.")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.command()
    @commands.bot_has_permissions(manage_roles=True)
    @mod_only()
    async def unmute(self, ctx, members: Greedy[discord.Member]):
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
                try:
                    await member.send(f"You are manually unmuted in **{ctx.guild.name}**.")
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.command()
    @commands.bot_has_permissions(ban_members=True)
    @mod_only()
    async def unban(self, ctx, members: Greedy[discord.User]):
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
                try:
                    await member.send(f"You are manually unbanned in **{ctx.guild.name}**.")
                except (discord.Forbidden, discord.HTTPException):
                    pass
                async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.guild\")=? "
                                      "AND json_extract(eventdata, \"$.member\")=? AND eventtype=?",
                                      (ctx.guild.id, member.id, "unban")) as cur:
                    async for row in cur:
                        await scheduler.canceltask(row[0])

    @commands.command()
    @mod_only()
    async def testmod(self, ctx):
        await ctx.reply("Hello moderator!")

    @commands.command()
    @mod_only()
    async def warn(self, ctx, user: discord.Member, points: typing.Optional[float] = 1, *,
                   reason="No reason provided."):
        assert points > 0
        if points > 1:
            points = round(points, 1)
        now = datetime.now(tz=timezone.utc)
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, reason, points)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, user.id, ctx.author.id,
                              int(now.timestamp()), reason, points))
            await db.commit()
        await ctx.reply(f"Warned {user.mention} with {points} infraction point{'' if points == 1 else 's'} for: "
                        f"`{discord.utils.escape_mentions(reason)}`")
        await on_warn(user)

    @commands.has_guild_permissions(kick_members=True, ban_members=True)
    @commands.command(aliases=["warnings"])
    async def warns(self, ctx, user: discord.Member):
        embed = discord.Embed(title=f"Warns for {user.display_name}", color=discord.Color(0xB565D9),
                              description=user.mention)
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id, issuedby, issuedat, reason, deactivated FROM warnings "
                                  "WHERE user=? AND server=? ORDER BY issuedat DESC",
                                  (user.id, ctx.guild.id)) as cursor:
                now = datetime.now(tz=timezone.utc)
                async for warn in cursor:
                    issuedby = await self.bot.fetch_user(warn[1])
                    issuedat = humanize.naturaltime(datetime.fromtimestamp(warn[2], tz=timezone.utc), when=now)
                    reason = warn[3]
                    embed.add_field(name=f"Warn ID #{warn[0]}{' (Deleted)' if warn[4] else ''}",
                                    value=
                                    f"Reason: {reason}\n"
                                    f"Issued by: {issuedby.mention}\n"
                                    f"Issued {issuedat}")
                if not embed.fields:
                    embed.add_field(name="No Warns", value="This user has no warns.")
        await ctx.reply(embed=embed)

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
