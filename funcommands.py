import random
import re
import typing

import discord
from discord.ext import commands


def stringshuffle(string):
    if len(string) <= 1:
        return string
    while (shstring := "".join(random.sample(string, len(string)))) == string:
        pass
    return shstring


def shuffleword(word, threshold=3):
    if len(word) < threshold:
        return stringshuffle(word)
    else:
        return word[0] + stringshuffle(word[1:-1]) + word[-1]


def wordshuffle(words, threshold=3):
    return re.sub(r"\w+", lambda x: shuffleword(x.group(0), threshold), words)


class FunCommands(commands.Cog, name="Fun"):
    """
    commands for entertainment
    """

    def __init__(self, bot):
        self.bot = bot
        self.regionals = {'a': '\N{REGIONAL INDICATOR SYMBOL LETTER A}', 'b': '\N{REGIONAL INDICATOR SYMBOL LETTER B}',
                          'c': '\N{REGIONAL INDICATOR SYMBOL LETTER C}',
                          'd': '\N{REGIONAL INDICATOR SYMBOL LETTER D}', 'e': '\N{REGIONAL INDICATOR SYMBOL LETTER E}',
                          'f': '\N{REGIONAL INDICATOR SYMBOL LETTER F}',
                          'g': '\N{REGIONAL INDICATOR SYMBOL LETTER G}', 'h': '\N{REGIONAL INDICATOR SYMBOL LETTER H}',
                          'i': '\N{REGIONAL INDICATOR SYMBOL LETTER I}',
                          'j': '\N{REGIONAL INDICATOR SYMBOL LETTER J}', 'k': '\N{REGIONAL INDICATOR SYMBOL LETTER K}',
                          'l': '\N{REGIONAL INDICATOR SYMBOL LETTER L}',
                          'm': '\N{REGIONAL INDICATOR SYMBOL LETTER M}', 'n': '\N{REGIONAL INDICATOR SYMBOL LETTER N}',
                          'o': '\N{REGIONAL INDICATOR SYMBOL LETTER O}',
                          'p': '\N{REGIONAL INDICATOR SYMBOL LETTER P}', 'q': '\N{REGIONAL INDICATOR SYMBOL LETTER Q}',
                          'r': '\N{REGIONAL INDICATOR SYMBOL LETTER R}',
                          's': '\N{REGIONAL INDICATOR SYMBOL LETTER S}', 't': '\N{REGIONAL INDICATOR SYMBOL LETTER T}',
                          'u': '\N{REGIONAL INDICATOR SYMBOL LETTER U}',
                          'v': '\N{REGIONAL INDICATOR SYMBOL LETTER V}', 'w': '\N{REGIONAL INDICATOR SYMBOL LETTER W}',
                          'x': '\N{REGIONAL INDICATOR SYMBOL LETTER X}',
                          'y': '\N{REGIONAL INDICATOR SYMBOL LETTER Y}', 'z': '\N{REGIONAL INDICATOR SYMBOL LETTER Z}',
                          '0': '0⃣', '1': '1⃣', '2': '2⃣', '3': '3⃣',
                          '4': '4⃣', '5': '5⃣', '6': '6⃣', '7': '7⃣', '8': '8⃣', '9': '9⃣', '!': '\u2757',
                          '?': '\u2753'}

    @commands.command()
    async def owoify(self, ctx, *, text=None):
        """
        sends your message like a furry would

        replaces r and l with w

        :param ctx: discord context
        :param text: the text to "owoify". defaults to last message in channel
        :return: owoified text
        """
        if text is None:
            messages = await ctx.channel.history(limit=1, before=ctx.message).flatten()
            text = messages[0].content
        await ctx.reply(
            text.replace("r", "w").replace("R", "W").replace("l", "w").replace("L", "W").replace("@", "\\@") + " owo~")

    @commands.command()
    async def sparkle(self, ctx, *, text=None):
        """
        Gives your text a little ✨ *e x t r a   f l a i r* ✨
        :param ctx: discord context
        :param text: the text to "sparkle". defaults to last message in channel
        :return: sparkled text
        """
        if text is None:
            messages = await ctx.channel.history(limit=1, before=ctx.message).flatten()
            text = messages[0].content
        await ctx.reply(f"✨ *{' '.join(text)}* ✨")

    @commands.command()
    async def clap(self, ctx, *, text=None):
        """
        make your point like👏a👏twitter👏user👏would
        :param ctx: discord context
        :param text: the text to "clap". defaults to last message in channel
        :return: clapped text
        """
        if text is None:
            messages = await ctx.channel.history(limit=1, before=ctx.message).flatten()
            text = messages[0].content
        await ctx.reply("👏".join(text.split(" ")))

    @commands.command()
    async def regional(self, ctx, *, msg=None):
        """
        make your text 🇱​🇦​🇷​🇬​🇪
        :param ctx:
        :param msg: the text to make large
        :return: the larged text
        """
        if msg is None:
            messages = await ctx.channel.history(limit=1, before=ctx.message).flatten()
            msg = messages[0].content
        """Replace letters with regional indicator emojis"""
        msg = list(msg)
        regional_list = [self.regionals[x.lower()] if x.isalnum() or x in ["!", "?"] else x for x in msg]
        regional_output = '\u200b'.join(regional_list)
        await ctx.reply(regional_output)

    @commands.command(aliases=["8ball", "magicball", "balls"])
    async def ball(self, ctx, *, question=None):
        """
        ask the magic 8ball a question 🎱
        :param ctx:
        :param question: the question to ask, defaults to last messagein channel
        :return: its answer
        """
        if question is None:
            messages = await ctx.channel.history(limit=1, before=ctx.message).flatten()
            question = messages[0].content
        options = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]
        embed = discord.Embed(color=discord.Colour(0xffffff))
        embed.set_thumbnail(url="https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f3b1.png")
        embed.add_field(name="You asked", value=question)
        embed.add_field(name="The 8ball says...", value=random.choice(options))
        await ctx.reply(embed=embed)

    @commands.command(aliases=["gender", "sexuality", "lgbtq", "queer"])
    async def identity(self, ctx):
        """
        generates a random new lgbtq identity
        :param ctx:
        :return: the identity
        """
        prefixes = [
            "non-",
            "demi",
            "bi",
            "hetero",
            "homo",
            "pan",
            "inter",
            "a",
            "trans",
            "gender",
            "allo",
            "teck"
        ]
        center = [
            "sexual",
            "gender",
            "sex",
            "binary",
            "questioning",
            "bian",
            "romantic",
            "amorous"
        ]
        suffixes = [
            "phobic",
            "fluid",
            "supremacist",
            "queer",
            "flexible",
        ]
        out = []
        for i in range(random.randint(1, 4)):
            p = random.choice(prefixes)
            c = random.choice(center)
            s = random.choice(suffixes)
            out.append(random.choice([f"{p}{c}{s}"] * 3 + [
                f"{p}{s}",
                f"{c}{s}",
                f"{p}{c}"
            ]))
        await ctx.reply(f"🏳️‍🌈 {' '.join(out)}")

    @commands.command(aliases=["drunktype", "shuffle", "shuffletype"])
    async def drunk(self, ctx: commands.Context, threshold: typing.Optional[int] = 4, *, text: str):
        """
        teyps your txet ni a dkeurnn wya

        :param ctx: dc
        :param threshold: how long a word must be to force the first and last characters to be the same
        :param text: the text to drunk type
        :return: yuro txet
        """
        assert threshold >= 0
        await ctx.reply(wordshuffle(text, threshold))


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
