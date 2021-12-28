import datetime
import typing

import aiosqlite
import nextcord as discord
from nextcord.ext import commands

import moderation
import modlog
import scheduler
from clogs import logger


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
            # cancel all existing birthday events
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.user\")=? "
                                  "AND eventtype=?",
                                  (ctx.author.id, "birthday")) as cur:
                async for event in cur:
                    await scheduler.canceltask(event[0], db)
            # insert birthday into db
            await db.execute(
                "REPLACE INTO birthdays(user,birthday) "
                "VALUES (?,?)",
                (ctx.author.id, birthday.timestamp()))
            await db.commit()
        # calculate next birthday
        now = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=tz)))
        thisyear = now.year
        nextbirthday = birthday
        while nextbirthday < now:
            try:
                nextbirthday = nextbirthday.replace(year=thisyear)
            except ValueError as e:  # leap years are weird
                logger.debug(str(e))
            thisyear += 1
        # schedule birthday event on next birthday
        await scheduler.schedule(nextbirthday, "birthday",
                                 {"user": ctx.author.id, "birthday": birthday.timestamp()})
        await ctx.reply(f"Set birthday to <t:{int(birthday.timestamp())}:f>")

    @commands.command()
    @moderation.mod_only()
    async def birthdaycategory(self, ctx, *, category: typing.Optional[discord.CategoryChannel] = None):
        """
        Set the category for birthday channels to be created, or disable them.

        :param ctx: discord context
        :param category: The ID of the category. Leave blank to disable birthday messages for the server.
        """
        if category is None:
            await moderation.update_server_config(ctx.guild.id, "birthday_category", None)
            await ctx.reply("✔️ Removed server birthday category and disabled birthday messages.")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) removed "
                                f"the server birthday category.", ctx.guild.id, modid=ctx.author.id)
        else:
            await moderation.update_server_config(ctx.guild.id, "birthday_category", category.id)
            await ctx.reply(f"✔️ Set birthday category to **{category.name}**")
            await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) set the "
                                f"server birthday category to **{category.name}**.", ctx.guild.id, modid=ctx.author.id)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def setotherbirthday(self, ctx: commands.Context, user: discord.User,  year: int, month: int, day: int,
                               tz: float = 0):
        """
        set someone else's birthday


        :param ctx: discord context
        :param user: the person to set their birthday
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
            # cancel all existing birthday events
            async with db.execute("SELECT id FROM schedule WHERE json_extract(eventdata, \"$.user\")=? "
                                  "AND eventtype=?",
                                  (user.id, "birthday")) as cur:
                async for event in cur:
                    await scheduler.canceltask(event[0], db)
            # insert birthday into db
            await db.execute(
                "REPLACE INTO birthdays(user,birthday) "
                "VALUES (?,?)",
                (user.id, birthday.timestamp()))
            await db.commit()
        # calculate next birthday
        now = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=tz)))
        thisyear = now.year
        nextbirthday = birthday
        while nextbirthday < now:
            try:
                nextbirthday = nextbirthday.replace(year=thisyear)
            except ValueError as e:  # leap years are weird
                logger.debug(str(e))
            thisyear += 1
        # schedule birthday event on next birthday
        await scheduler.schedule(nextbirthday, "birthday",
                                 {"user": user.id, "birthday": birthday.timestamp()})
        await ctx.reply(f"Set birthday to <t:{int(birthday.timestamp())}:f>")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
