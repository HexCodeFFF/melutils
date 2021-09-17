import io

import aiosqlite
import discord
from discord.ext import commands

from clogs import logger
from moderation import mod_only
from modlog import modlog


def alphanumeric(argument: str):
    return ''.join(i for i in argument if i.isalnum())


class MacroCog(commands.Cog, name="Macros"):
    """
    Create and use "macros", text snippets sendable with a command
    """
    def __init__(self, bot):
        self.bot = bot

    @mod_only()
    @commands.command(aliases=["createmacro", "newmacro", "setmacro"])
    async def addmacro(self, ctx: commands.Context, name: alphanumeric, *, content):
        """
        creates a macro

        :param ctx: discord context
        :param name: name of the macro
        :param content: macro content
        """
        async with aiosqlite.connect("database.sqlite") as db:
            await db.execute(
                "REPLACE INTO macros(server,name,content) VALUES (?,?,?)",
                (ctx.guild.id, name, content))
            await db.commit()
        await ctx.reply(f"✔️ Added macro `{name}`.")
        await modlog(f"{ctx.author.mention} (`{ctx.author}`) added macro `{name}`.", ctx.guild.id, modid=ctx.author.id)

    @mod_only()
    @commands.command(aliases=["deletemacro"])
    async def removemacro(self, ctx: commands.Context, name):
        """
        removes a macro

        :param ctx: discord context
        :param name: name of the macro
        """
        async with aiosqlite.connect("database.sqlite") as db:
            cur = await db.execute(
                "DELETE FROM macros WHERE server=? AND name=?",
                (ctx.guild.id, name))
            await db.commit()
        if cur.rowcount > 0:
            await ctx.reply(f"✔️ Deleted macro {name}.")
            await modlog(f"{ctx.author.mention} (`{ctx.author}`) deleted macro `{name}`.", ctx.guild.id,
                         modid=ctx.author.id)
        else:
            await ctx.reply("⚠️ No macro found with that name!")

    @commands.command(aliases=["m", "tag"])
    async def macro(self, ctx: commands.Context, name):
        """
        send the content of a macro
        :param ctx: discord content
        :param name: the name of the macro
        :return: macro content
        """
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT content FROM macros WHERE server=? AND name=?", (ctx.guild.id, name)) as cur:
                result = await cur.fetchone()
        if result is None or result[0] is None:
            await ctx.reply("⚠️ No macro found with that name!")
        else:
            await ctx.send(result[0], allowed_mentions=discord.AllowedMentions.none())

    @commands.command(aliases=["listmacros", "allmacros", "lm"])
    async def macros(self, ctx: commands.Context):
        """
        list all available macros
        """
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT name FROM macros WHERE server=?",
                                  (ctx.guild.id,)) as cursor:
                macros = [i[0] for i in await cursor.fetchall()]
        outstr = f"{len(macros)} macro{'' if len(macros) == 1 else 's'}: {', '.join(macros)}"
        if len(outstr) < 2000:
            await ctx.reply(outstr, allowed_mentions=discord.AllowedMentions.none())
        else:
            with io.StringIO() as buf:
                buf.write(outstr)
                buf.seek(0)
                await ctx.reply(f"{len(macros)} macro{'' if len(macros) == 1 else 's'}.",
                                file=discord.File(buf, filename="macros.txt"))
        logger.debug(macros)
    # command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
