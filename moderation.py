import aiosqlite
import discord
from discord.ext import commands
import typing
from timeconverter import TimeConverter
import time
from datetime import datetime, timezone
import humanize
from clogs import logger


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    # TODO: implement proper mod role
    @commands.has_guild_permissions(kick_members=True, ban_members=True)
    @commands.command()
    async def warn(self, ctx, user: discord.Member, warn_length: typing.Optional[TimeConverter] = 604800, *,
                   reason="No reason provided."):
        async with aiosqlite.connect("database.sqlite") as db:

            await db.execute("INSERT INTO warnings(server, user, issuedby, issuedat, expires, reason)"
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (ctx.guild.id, user.id, ctx.author.id,
                              int(datetime.now(tz=timezone.utc).timestamp()),
                              int(time.time() + warn_length), reason))
            await db.commit()
        await ctx.reply(f"Warned {user.mention} for: `{reason}`")

    @commands.has_guild_permissions(kick_members=True, ban_members=True)
    @commands.command(aliases=["warnings"])
    async def warns(self, ctx, user: discord.Member):
        embed = discord.Embed(title=f"Warns for {user.display_name}", color=discord.Color(0xB565D9))
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute(
                    "SELECT id, issuedby, issuedat, expires, reason, deactivated FROM warnings WHERE user=?",
                    (user.id,)) as cursor:
                async for warn in cursor:
                    issuedby = await self.bot.fetch_user(warn[1])
                    issuedat = humanize.naturaltime(datetime.fromtimestamp(warn[2], tz=timezone.utc),
                                                    when=datetime.now(tz=timezone.utc))
                    expires = humanize.precisetime(datetime.fromtimestamp(warn[3], tz=timezone.utc),
                                                   when=datetime.now(tz=timezone.utc), format="%.0f")
                    reason = warn[4]
                    embed.add_field(name=f"Warn ID #{warn[0]}",
                                    value=
                                    f"Reason: {reason}\n"
                                    f"Issued by: {issuedby.mention}\n"
                                    # these 2 are naturaltimes from humanize so no colon makes sense
                                    f"Issued {issuedat}\n"
                                    f"Expires {expires}")
        await ctx.reply(embed=embed)

    @commands.command()
    async def delwarn(self, ctx, warnid: int):
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute("DELETE FROM warnings WHERE id=?", (warnid,))
            await db.commit()


# command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
