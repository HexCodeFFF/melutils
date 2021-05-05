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
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            raise commands.CheckFailure("Moderation commands must be run in a server.")
        if ctx.author.permissions.administrator:
            return True

    return commands.check(predicate)


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    # TODO: implement proper mod role
    @commands.has_guild_permissions(kick_members=True, ban_members=True)
    @commands.command()
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
