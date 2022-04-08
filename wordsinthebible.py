import io
import os.path
import re
import typing

import aiohttp
import aiosqlite
import discord.utils
import openpyxl
import openpyxl.cell
from nextcord.ext import commands


async def request(url: str):
    async with aiohttp.ClientSession(headers={'Connection': 'keep-alive'}) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


async def parse_bible():
    if os.path.isfile("bible.sqlite"):
        os.remove("bible.sqlite")
    db = await aiosqlite.connect("bible.sqlite")
    await db.execute("""
create table verses
(
    verse      string,
    short_trns string,
    content    string,
    constraint table_name_pk
        primary key (verse, short_trns)
);
""")
    if os.path.isfile("bibles.xlsx"):
        workbook = openpyxl.load_workbook(open("bibles.xlsx", "rb"), read_only=True)
    else:
        biblebytes = await request("https://openbible.com/xls/bibles.xlsx")
        workbook = openpyxl.load_workbook(io.BytesIO(biblebytes), read_only=True)
    worksheet = workbook.active
    worksheet.reset_dimensions()
    short_trns = {}
    try:
        for i, row in enumerate(worksheet.rows):
            row: typing.Tuple[openpyxl.cell.read_only.ReadOnlyCell]
            if i == 0:  # header cell
                for cell in row:
                    cell: openpyxl.cell.read_only.ReadOnlyCell
                    if not isinstance(cell, openpyxl.cell.read_only.EmptyCell):
                        short_trns[cell.column] = cell.value
            elif i > 1:  # value row
                verse = row[0].value
                for cell in row[1:]:
                    if hasattr(cell, "value") and not isinstance(cell, openpyxl.cell.read_only.EmptyCell):
                        col = cell.column
                        st = short_trns[col]
                        content = cell.value
                        await db.execute("INSERT INTO verses VALUES (?,?,?)", (verse, st, content))
    except Exception as e:
        # for reasons i do not understand it crashes if i dont put this here
        print(e)
        raise e
    workbook.close()
    await db.commit()


class BibleCog(commands.Cog, name="Words in the Bible"):
    """
    find out if these words are in the bible
    """

    def __init__(self, bot):
        self.bot: commands.Bot = bot

    @commands.command()
    @commands.max_concurrency(1)
    @commands.is_owner()
    async def buildbibledb(self, ctx: commands.Context, overwrite: bool = False):
        """
        download and build the bible database that powers this cog.
        :param ctx:
        :param overwrite: set to true to make database even if it exists
        """
        if os.path.isfile("bible.sqlite") and not overwrite:
            await ctx.reply("The database already exists. Run `m.buildbibledb y` to overwrite it.")
        else:
            msg = await ctx.reply("This will take a moment and may interrupt bot activities...")
            async with ctx.typing():
                await parse_bible()
            await msg.delete()
            await ctx.reply("Done!")

    # command here
    @commands.command()
    async def wordsinbible(self, ctx: commands.Context, *, words: str):
        """show which words of a phrase are in the bible"""
        if not os.path.isfile("bible.sqlite"):
            await ctx.reply("Bible DB not setup, please run `m.buildbibledb`.")
            return
        words = discord.utils.escape_markdown(words)
        uniquewords = set(re.findall("[a-zA-Z]+", words))
        iswordinbible = {}
        async with aiosqlite.connect("bible.sqlite") as biblecon:
            for word in uniquewords:
                async with biblecon.execute("SELECT * FROM verses WHERE content LIKE ('%' || ? || '%') LIMIT 1",
                                            (word,)) as cur:
                    res = await cur.fetchone()
                iswordinbible[word] = res is not None
        inbible = set(filter(lambda w: w in iswordinbible and iswordinbible[w], uniquewords))
        notinbible = uniquewords - inbible

        if len(notinbible) == 0:
            await ctx.reply(f"🙏 all of these words are in the bible")
        elif len(inbible) == 0:
            await ctx.reply(f"😈 none of these words are in the bible")
        else:

            def boldnonbiblicalwords(w: re.Match):
                w = w.group(0)
                if w in notinbible:
                    return f"**{w}**"
                else:
                    return w

            out = re.sub("[a-zA-Z]+", boldnonbiblicalwords, words, flags=re.RegexFlag.IGNORECASE)

            await ctx.reply(f"{len(inbible)}/{len(uniquewords)} ({round((len(inbible) / len(uniquewords)) * 100)}%)"
                            f" are in the bible.\n"
                            f"found {len(notinbible)} words not in the bible:\n{out}")

    @commands.command()
    async def findinbible(self, ctx: commands.Context, limit: typing.Optional[int] = 1, *, words: str):
        """find a specific phrase in the bible"""
        if not os.path.isfile("bible.sqlite"):
            await ctx.reply("Bible DB not setup, please run `m.buildbibledb`.")
            return
        assert 0 < limit < 6
        async with aiosqlite.connect("bible.sqlite") as biblecon:
            async with biblecon.execute("SELECT verse, short_trns, content FROM verses "
                                        "WHERE content LIKE ('%' || ? || '%') GROUP BY verse ORDER BY random() LIMIT ?",
                                        (words, limit)) as cur:
                res = await cur.fetchall()
        if not res:
            await ctx.reply(f"Could not find this in the bible.")
        else:
            out = []
            for row in res:
                verse, short_trns, content = row
                content = re.sub(re.escape(words), lambda x: f"**{x.group(0)}**", content,
                                 flags=re.RegexFlag.IGNORECASE)
                out.append(f"{verse} ({short_trns})\n> {content}")
            out = "\n".join(out)
            if len(out) > 2000:
                out = out[:2000 - 5] + "\n\n..."
            await ctx.reply(out)

    @commands.command()
    async def countinbible(self, ctx: commands.Context, *, words: str):
        """count how many times a phrase occurs among 14 bible translations"""
        if not os.path.isfile("bible.sqlite"):
            await ctx.reply("Bible DB not setup, please run `m.buildbibledb`.")
            return
        async with aiosqlite.connect("bible.sqlite") as biblecon:
            async with biblecon.execute(
                    "SELECT SUM((LENGTH(content) - LENGTH(REPLACE(LOWER(content), LOWER(?), ''))) / "
                    "LENGTH(?)) FROM verses",
                    (words, words)) as cur:
                sm = (await cur.fetchone())[0]
        await ctx.reply(f"Found this phrase {sm} time{'' if sm == 1 else 's'} among 14 English Bible translations.\n"
                        f"Average of {round(sm / 14, 1)} per translation. See `m.findinbible` to see what they are.")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx, ...): -> function(self, ctx, ...)
bot -> self.bot
'''
