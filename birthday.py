import datetime
import typing

import aiosqlite
import discord
from discord.ext import commands
from clogs import logger
from moderation import mod_only
from modlog import modlog


class BirthdayCog(commands.Cog, name="Birthday Commands"):
    def __init__(self, bot):
        self.bot = bot

    # command here
    @commands.command()
    async def setbirthday(self, ctx: commands.Context, year: int, month: int, day: int, tz: float = 0):
        try:
            birthday = datetime.datetime(year=year, month=month, day=day,
                                         tzinfo=datetime.timezone(datetime.timedelta(hours=tz)))
        except ValueError as e:
            await ctx.reply(str(e))
            return

        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute(
                "REPLACE INTO birthdays(user,birthday) "
                "VALUES (?,?)",
                (ctx.author.id, birthday.timestamp()))
            await db.commit()
        await ctx.reply(f"Set birthday to <t:{birthday.timestamp()}:f>")

'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
