import asyncio
import io
import json
import re
import typing
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands
from discord.ext.commands import PartialEmojiConversionFailure
from discord.ext.commands.cooldowns import BucketType

import humanize
import scheduler
from clogs import logger
from timeconverter import TimeConverter


async def fetch(session, url):
    async with session.get(url) as response:
        if response.status != 200:
            response.raise_for_status()
        return await response.read()


async def fetch_all(session, urls):
    tasks = []
    for url in urls:
        task = asyncio.create_task(fetch(session, url))
        tasks.append(task)
    results = await asyncio.gather(*tasks)
    return results


class UtilityCommands(commands.Cog, name="Utility"):
    """
    miscellaneous utility commands
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

    @commands.cooldown(1, 60, BucketType.guild)
    @commands.command()
    async def messagecount(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        async with ctx.channel.typing():
            count = 0
            async for _ in channel.history(limit=None):
                count += 1
            await ctx.reply(f"There are {count} messages in {channel.mention}.")

    @commands.cooldown(1, 60, BucketType.guild)
    @commands.command()
    async def mediacount(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        async with ctx.channel.typing():
            count = 0
            async for msg in channel.history(limit=None):
                if len(msg.embeds):
                    for embed in msg.embeds:
                        if embed.type in ["image", "video", "audio", "gifv"]:
                            count += 1
                if len(msg.attachments):
                    count += len(msg.attachments)
            await ctx.reply(f"There are {count} media in {channel.mention}.")

    @commands.command(aliases=["remind", "remindme", "messagemein"])
    async def reminder(self, ctx, when: TimeConverter, *, reminder):
        scheduletime = datetime.now(tz=timezone.utc) + when
        await scheduler.schedule(scheduletime, "message",
                                 {"channel": ctx.author.id, "message": f"Here's your reminder: {reminder}"})
        now = datetime.now(tz=timezone.utc)
        remindertext = humanize.precisetime(scheduletime, when=now, format="%.0f")
        await ctx.reply(f"✔️ I'll remind you {remindertext}.")

    @commands.cooldown(1, 60 * 60 * 24, BucketType.guild)
    @commands.command()
    async def emojicount(self, ctx):
        replystr = f"Gathering emoji statistics for **{ctx.guild.name}**. This may take a while."
        replymsg = await ctx.reply(replystr)
        messagecount = 0
        emojicount = 0
        async with ctx.channel.typing():
            emojiregex = r"<a?:\w{2,32}:(\d{18,22})>"
            counts = defaultdict(int)
            for channel in ctx.guild.text_channels:
                logger.debug(f"counting emojis in {channel}")
                if channel.id == 830588015243427890:
                    continue
                async for msg in channel.history(limit=None):
                    if messagecount % 1000 == 0:
                        await replymsg.edit(content=f"{replystr}\nCurrently scanning:{channel.mention}"
                                                    f"\nScanned {messagecount} messages.\nFound {emojicount} emojis.\n")
                    messagecount += 1
                    for match in re.finditer(emojiregex, msg.content):
                        emoji = match.group(0)
                        counts[emoji] += 1
                        emojicount += 1
            await replymsg.edit(content=f"{replystr}\nScanned {messagecount} messages.\nFound {emojicount} emojis.\n")
            sortedcount = {k: v for k, v in sorted(counts.items(), key=lambda item: item[1], reverse=True)}
            with io.BytesIO() as buf:
                buf.write(json.dumps(sortedcount, indent=4).encode())
                buf.seek(0)
                await ctx.reply(file=discord.File(buf, filename="emojis.json"))

    @commands.bot_has_permissions(manage_messages=True)
    @commands.command(aliases=["cw", "tw", "censor", "s", "sp", "spoil"])
    async def spoiler(self, ctx: commands.Context, *, content=""):
        """
        Spoiler a message and its attachments.
        If you have manage message permissions, you can reply to a message with just `m.spoiler` to reupload the message spoilered and delete the original.
        """
        async with ctx.typing():
            outattachments = []
            for att in ctx.message.attachments:
                outattachments.append(await att.to_file(spoiler=True))
            embed = discord.Embed().set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar_url)
            if content:
                content = f"|| {discord.utils.escape_markdown(content)} ||"
            if content or outattachments:
                await asyncio.gather(
                    ctx.send(content=content, files=outattachments, embed=embed,
                             allowed_mentions=discord.AllowedMentions.none()),
                    ctx.message.delete()
                )
                return
            elif ctx.message.reference and (ctx.author.permissions_in(
                    ctx.channel).manage_messages or ctx.message.reference.resolved.author == ctx.author):
                outattachments = []
                for att in ctx.message.reference.resolved.attachments:
                    outattachments.append(await att.to_file(spoiler=True))
                embed = discord.Embed().set_author(name=ctx.message.reference.resolved.author.display_name,
                                                   icon_url=ctx.message.reference.resolved.author.avatar_url)
                embed.set_footer(text=f"Spoilered by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)
                content = f"|| {discord.utils.escape_markdown(ctx.message.reference.resolved.content)} ||" \
                    if ctx.message.reference.resolved.content else ""
                await asyncio.gather(
                    ctx.send(content=content, files=outattachments, embed=embed,
                             allowed_mentions=discord.AllowedMentions.none()),
                    ctx.message.delete(),
                    ctx.message.reference.resolved.delete()
                )
                return
            await ctx.reply("❌ no content to spoiler or no replied message to spoiler.")

    @commands.command()
    @commands.bot_has_permissions(manage_webhooks=True)
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 30, BucketType.channel)
    async def fakeconversation(self, ctx: commands.Context, *, content: str):
        """
        Generate a fake conversation using webhooks.
        """
        webhook = None
        webhooks = await ctx.channel.webhooks()
        for w in webhooks:
            if w.user == self.bot.user:
                webhook = w
                break
        if webhook is None:
            webhook = await ctx.channel.create_webhook(name="MelUtils Webhook")
        for line in content.split("\n"):
            if line[0].lower() in self.regionals:
                chars = []
                for char in self.regionals[line[0].lower()]:
                    chars.append(f"{ord(char):x}")  # get hex code of char
                chars = "-".join(chars).replace("/", "")
                # we like to troll
                url = f"https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/{chars}.png"
                await webhook.send(line[1:], username=f"Member {line[0].upper()}", avatar_url=url)
                await asyncio.sleep(0.5)

    async def partial_emoji_list_to_uploaded_zip(self, ctx: commands.Context, emojis: typing.List[
        typing.Union[discord.Emoji, discord.PartialEmoji]]):
        emoji_bytes = await asyncio.gather(*[emoji.url.read() for emoji in emojis])
        with io.BytesIO() as archive:
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_archive:
                for i, emoji in enumerate(emoji_bytes):
                    zip_archive.writestr(f"{i}_{emojis[i].name}.{'gif' if emojis[i].animated else 'png'}",
                                         bytes(emoji))
            archive.seek(0)
            await ctx.reply(file=discord.File(fp=archive, filename="emojis.zip"))

    @commands.command()
    @commands.cooldown(1, 30, BucketType.user)
    async def zipemojis(self, ctx: commands.Context, *messages: discord.Message):
        async with ctx.typing():
            regex = r"<(a?):([a-zA-Z0-9\_]+):([0-9]+)>"
            emojis = []
            for m in messages:
                for em in re.finditer(regex, m.content):
                    try:
                        pec = commands.PartialEmojiConverter()
                        em = await pec.convert(ctx=ctx, argument=em.group(0))
                        emojis.append(em)
                    except PartialEmojiConversionFailure:
                        pass
            if len(emojis) == 0:
                await ctx.reply("No emojis found.")
                return
            await self.partial_emoji_list_to_uploaded_zip(ctx, emojis)

    @commands.command()
    @commands.cooldown(1, 30, BucketType.guild)
    async def archiveserveremojis(self, ctx: commands.Context):
        async with ctx.typing():
            await self.partial_emoji_list_to_uploaded_zip(ctx, ctx.guild.emojis)


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
