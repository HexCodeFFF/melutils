import datetime

import aiosqlite
from discord.ext import commands


class BirthdayCog(commands.Cog, name="Birthday Commands"):
    def __init__(self, bot):
        self.bot = bot

    # command here
    @commands.command()
    async def setbirthday(self, ctx: commands.Context, year: int, month: int, day: int, tz: float = 0):
        """
        set your birthday to get a celebration channel on your birthday

        :param ctx: discord context
        :param year: year of birth (used for age)
        :param month: month of birthday
        :param day: day of birthday
        :param tz: timezone of birthday in UTC offset (i.e. CST would be `-6` since it is UTC-6)
        """
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
        await ctx.reply(f"Set birthday to <t:{int(birthday.timestamp())}:f>")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
