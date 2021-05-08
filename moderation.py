import aiosqlite
import discord
from discord.ext import commands
import typing
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
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT COUNT(guild) FROM server_config") as cur:
            guilds = await cur.fetchone()
        if guilds[0]:  # if there already is a row for this guild
            await db.execute(f"UPDATE server_config SET {config} = ? WHERE guild=?", (value, server))
        else:  # if not, make one
            await db.execute(f"INSERT INTO server_config(guild, {config}) VALUES (?, ?)", (server, value))
        await db.commit()


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def setmodrole(self, ctx, *, role: typing.Union[discord.Role, None] = None):
        if role is None:
            await update_server_config(ctx.guild.id, "mod_role", None)
            await ctx.reply("✔️ Removed server moderator role.")
        else:
            await update_server_config(ctx.guild.id, "mod_role", role.id)
            await ctx.reply(f"✔️ Set server moderator role to **{discord.utils.escape_mentions(role.name)}**")

    @commands.command()
    @mod_only()
    async def testmod(self, ctx):
        await ctx.reply("Hello moderator!")

    @commands.command()
    @mod_only()
    async def warn(self, ctx, user: discord.Member, warn_length: typing.Optional[TimeConverter] = timedelta(weeks=1), *,
                   reason="No reason provided."):
        now = datetime.now(tz=timezone.utc)
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, expires, reason)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, user.id, ctx.author.id,
                              int(now.timestamp()),
                              int((now + warn_length).timestamp()), reason))
            await db.commit()
        await ctx.reply(f"Warned {user.mention} for: `{reason}`")

    @commands.has_guild_permissions(kick_members=True, ban_members=True)
    @commands.command(aliases=["warnings"])
    async def warns(self, ctx, user: discord.Member):
        embed = discord.Embed(title=f"Warns for {user.display_name}", color=discord.Color(0xB565D9),
                              description=user.mention)
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT id, issuedby, issuedat, expires, reason, deactivated FROM warnings "
                                  "WHERE user=? AND server=? ORDER BY issuedat DESC",
                                  (user.id, ctx.guild.id)) as cursor:
                now = datetime.now(tz=timezone.utc)
                async for warn in cursor:
                    issuedby = await self.bot.fetch_user(warn[1])
                    issuedat = humanize.naturaltime(datetime.fromtimestamp(warn[2], tz=timezone.utc), when=now)
                    expire_dt = datetime.fromtimestamp(warn[3], tz=timezone.utc)
                    warnexpired = expire_dt < now and not warn[5]
                    expires = humanize.precisetime(expire_dt, when=now, format="%.0f")
                    reason = warn[4]
                    embed.add_field(name=f"Warn ID #{warn[0]} ({'expired' if warnexpired else 'active'})",
                                    value=
                                    f"Reason: {reason}\n"
                                    f"Issued by: {issuedby.mention}\n"
                                    # these 2 are naturaltimes from humanize so no colon makes sense
                                    f"Issued {issuedat}\n"
                                    f"Expire{'d' if warnexpired else 's'} {expires}\n"
                                    f"{'Manually expired early.' if warn[5] else ''}")
                if not embed.fields:
                    embed.add_field(name="No Warns", value="This user has no warns.")
        await ctx.reply(embed=embed)

    @commands.is_owner()
    @commands.command()
    async def delwarn(self, ctx, *warnid: int):
        async with aiosqlite.connect("database.sqlite") as db:
            await db.executemany("DELETE FROM warnings WHERE id=?", [(i,) for i in warnid])
            await db.commit()
            await ctx.reply("✔️")


# command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
