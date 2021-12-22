import asyncio
import io
import json
import os
import random
import re
import string
import time
import typing
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp
import nextcord as discord
import humanize
from nextcord.ext import commands
from nextcord.ext.commands import PartialEmojiConversionFailure
from nextcord.ext.commands.cooldowns import BucketType

import scheduler
from clogs import logger
from timeconverter import TimeConverter


async def fetch_all(session, urls):
    tasks = []
    for url in urls:
        task = asyncio.create_task(fetch(session, url))
        tasks.append(task)
    results = await asyncio.gather(*tasks)
    return results


async def saveurl(url) -> bytes:
    """
    save a url to bytes
    :param url: web url of a file
    :return: bytes of result
    """
    async with aiohttp.ClientSession(headers={'Connection': 'keep-alive'}) as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
            else:
                resp.raise_for_status()


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
        """
        count the number of messages in a discord channel.
        :param ctx: discord context
        :param channel: the text channel to count the messages. if unspecified, uses this channel.
        :return: the number of messages
        """
        channel = channel or ctx.channel
        async with ctx.channel.typing():
            count = 0
            async for _ in channel.history(limit=None):
                count += 1
            await ctx.reply(f"There are {count} messages in {channel.mention}.")

    # @commands.cooldown(1, 60 * 60 * 24 * 7, BucketType.channel)
    @commands.is_owner()
    @commands.command()
    async def clonechannel(self, ctx, target: typing.Union[discord.TextChannel, discord.Thread],
                           destination: typing.Union[discord.TextChannel, discord.Thread]):
        """
        clones the content of one discord channel to another
        :param ctx: discord context
        :param target: the channel to clone
        :param destination: the channel to clone to
        """
        async with ctx.channel.typing():
            await destination.send(f"Cloning messages from {target.mention}")
            count = 0
            async for msg in target.history(limit=None, oldest_first=True):

                try:
                    embed = discord.Embed()
                    embed.set_author(name=msg.author.display_name, icon_url=msg.author.avatar.url)
                    embed.timestamp = msg.created_at
                    embed.description = msg.content
                    if msg.reference:
                        if msg.reference.resolved:
                            embed.add_field(name=f"Replying to *{msg.reference.resolved.author.display_name}*",
                                            value=msg.reference.resolved.content)
                    await destination.send(embeds=[embed] + msg.embeds,
                                           files=await asyncio.gather(*[att.to_file() for att in msg.attachments]))
                    count += 1
                except Exception as e:
                    await destination.send(f"Failed to clone message {msg.id}\n```{e}```")
                    logger.error(f"Failed to clone message {msg.id}")
                    logger.error(e, exc_info=(type(e), e, e.__traceback__))
            await destination.send(f"Cloned {count} message(s) from {target.mention}")

    @commands.cooldown(1, 60 * 60, BucketType.channel)
    @commands.command()
    async def mediacount(self, ctx, channel: discord.TextChannel = None):
        """
        count the amount of media in a discord channel.
        :param ctx: discord context
        :param channel: the text channel to count the media. if unspecified, uses this channel.
        :return: the amount of media
        """
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

    # @commands.cooldown(1, 60 * 60, BucketType.channel)
    @commands.command(hidden=True)
    @commands.is_owner()
    async def mediazip(self, ctx, channel: discord.TextChannel = None):
        """
        zip all media in channel
        :param ctx: discord context
        :param channel: the text channel to zip the media. if unspecified, uses this channel.
        :return: the amount of media
        """
        channel = channel or ctx.channel
        files = []
        exts = []
        async with ctx.channel.typing():
            async for msg in channel.history(limit=None):
                if len(msg.embeds):
                    for embed in msg.embeds:
                        if embed.type in ["image", "video", "audio", "gifv"]:
                            files.append(saveurl(embed.url))
                            exts.append(embed.url.split(".")[-1])
                if len(msg.attachments):
                    for att in msg.attachments:
                        files.append(att.read())
                        exts.append(att.url.split(".")[-1])
            filebytes = await asyncio.gather(*files)
            with io.BytesIO() as archive:
                with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_archive:
                    for i, f in enumerate(filebytes):
                        zip_archive.writestr(f"{i}.{exts[i]}",
                                             bytes(f))
                archive.seek(0, 2)
                size = archive.tell()
                archive.seek(0)
                if size < 8388119:
                    await ctx.reply(file=discord.File(fp=archive, filename="media.zip"))
                else:
                    hsize = humanize.filesize.naturalsize(size)
                    if not os.path.isdir("files"):
                        os.mkdir("files")
                    with open(temp_file_name("zip", "files/"), "wb+") as f:
                        f.write(archive.read())
                    await ctx.reply(f"File is {hsize}. Wrote to `files/media.zip`.")

    @commands.command(aliases=["remind", "remindme", "messagemein"])
    async def reminder(self, ctx, when: TimeConverter, *, reminder):
        """
        set a reminder.
        :param ctx: discord context
        :param when: how long from now to remind you
        :param reminder: the reminder text
        """
        now = datetime.now(tz=timezone.utc)
        scheduletime = now + when
        await scheduler.schedule(scheduletime, "message",
                                 {"channel": ctx.author.id, "message": f"Here's your reminder: {reminder}"})
        remindertext = humanize.precisetime(scheduletime, when=now, format="%.0f")
        await ctx.reply(f"✔️ I'll remind you {remindertext}.")
        # await ctx.reply(f"✔️ I'll remind you <t:{int(scheduletime.timestamp())}:R>.")

    @commands.cooldown(1, 60 * 60 * 24, BucketType.guild)
    @commands.command()
    async def emojicount(self, ctx):
        """
        count the amount of times each emoji was used in an entire server.
        :param ctx: discord context
        :return: a JSON file containing each emoji and how many usages were counted.
        """
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

        If you have manage message permissions,
        you can reply to a message with just `m.spoiler` to reupload the message spoilered and delete the original.

        :param ctx: discord context
        :param content: the message to spoiler.
        :return: the message and its attachments spoilered.
        """
        async with ctx.typing():
            outattachments = []
            for att in ctx.message.attachments:
                outattachments.append(await att.to_file(spoiler=True))
            embed = discord.Embed().set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
            if content:
                content = f"|| {discord.utils.escape_markdown(content)} ||"
            if content or outattachments:
                await asyncio.gather(
                    ctx.send(content=content, files=outattachments, embed=embed,
                             allowed_mentions=discord.AllowedMentions.none()),
                    ctx.message.delete()
                )
                return
            elif ctx.message.reference and (ctx.channel.permissions_for(
                    ctx.author).manage_messages or ctx.message.reference.resolved.author == ctx.author):
                outattachments = []
                for att in ctx.message.reference.resolved.attachments:
                    outattachments.append(await att.to_file(spoiler=True))
                embed = discord.Embed().set_author(name=ctx.message.reference.resolved.author.display_name,
                                                   icon_url=ctx.message.reference.resolved.author.avatar.url)
                embed.set_footer(text=f"Spoilered by {ctx.author.display_name}", icon_url=ctx.author.avatar.url)
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

        :param ctx: discord context
        :param content: the fake conversation. start a message with A-Z or 0-9 to differentiate members.
        :return: each fake webhook member will send a message in the current channel to create the conversation
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
        emoji_bytes = await asyncio.gather(*[emoji.read() for emoji in emojis])
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
        """
        zip all emojis contained in one or more messages.
        :param ctx: discord context
        :param messages: the ID(s) of messages containing emojis
        :return: a zip file containing any emojis found in the messages.
        """
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
        """
        zip every emoji in a server.
        :param ctx: discord context
        :return: zip file containing all emojis
        """
        async with ctx.typing():
            await self.partial_emoji_list_to_uploaded_zip(ctx, list(ctx.guild.emojis))

    async def sticker_list_to_uploaded_zip(self, ctx: commands.Context, stickers: tuple[discord.GuildSticker]):
        sticker_bytes = await asyncio.gather(*[sticker.read() for sticker in stickers])
        with io.BytesIO() as archive:
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_archive:
                for i, sticker in enumerate(sticker_bytes):
                    zip_archive.writestr(f"{i}_{stickers[i].name}."
                                         f"{'json' if stickers[i].format == discord.StickerFormatType.lottie else 'png'}",
                                         bytes(sticker))
            archive.seek(0)
            await ctx.reply(file=discord.File(fp=archive, filename="stickers.zip"))

    @commands.command()
    @commands.cooldown(1, 30, BucketType.guild)
    async def archiveserverstickers(self, ctx: commands.Context):
        """
        zip every sticker in a server.
        :param ctx: discord context
        :return: zip file containing all stickers
        """
        async with ctx.typing():
            await self.sticker_list_to_uploaded_zip(ctx, ctx.guild.stickers)

    @commands.command(aliases=["pong"])
    async def ping(self, ctx):
        """
        pong!
        :param ctx:
        :return: a message containing the API and websocket latency in ms.
        """
        start = time.perf_counter()
        message = await ctx.send("Ping...")
        end = time.perf_counter()
        duration = (end - start) * 1000
        await message.edit(content=f'🏓 Pong!\n'
                                   f'API Latency: `{round(duration)}ms`\n'
                                   f'Websocket Latency: `{round(self.bot.latency * 1000)}ms`')

    @commands.command(hidden=True)
    @commands.is_owner()
    async def sendallstaticemojis(self, ctx: commands.Context):
        msgs = await asyncio.gather(*[ctx.send(str(emoji)) for emoji in ctx.guild.emojis if not emoji.animated])
        await asyncio.gather(*[message.add_reaction("✅") for message in msgs])

    @commands.command(hidden=True)
    @commands.is_owner()
    async def sendallanimatedemojis(self, ctx: commands.Context):
        msgs = await asyncio.gather(*[ctx.send(str(emoji)) for emoji in ctx.guild.emojis if emoji.animated])
        await asyncio.gather(*[message.add_reaction("✅") for message in msgs])

    @commands.command(hidden=True)
    @commands.is_owner()
    async def sendallstickers(self, ctx: commands.Context):
        msgs = await asyncio.gather(*[ctx.send(stickers=[sticker]) for sticker in ctx.guild.stickers])
        await asyncio.gather(*[message.add_reaction("✅") for message in msgs])

    @commands.command()
    async def id(self, ctx: commands.Context,
                 obj: typing.Optional[typing.Union[discord.abc.GuildChannel, discord.User, discord.Guild,
                                                   discord.Thread, discord.PartialEmoji, discord.Role,
                                                   discord.Object]] = None):
        """
        gets the ID of a discord object
        :param ctx: discord context
        :param obj: a user, emoji, channel, guild, or role. will default to the author if not specified
        :return: the ID of the object.
        """
        if obj is None:
            obj = ctx.author
        if hasattr(obj, "mention"):
            await ctx.reply(f"{obj.mention}'s ID is `{obj.id}`", allowed_mentions=discord.AllowedMentions.none())
        else:
            await ctx.reply(f"{str(obj)}'s ID is `{obj.id}`", allowed_mentions=discord.AllowedMentions.none())


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''


async def fetch(session, url):
    async with session.get(url) as response:
        if response.status != 200:
            response.raise_for_status()
        return await response.read()


def temp_file_name(extension="png", tempdir="temp/"):
    while True:
        if extension is not None:
            name = f"{tempdir}{get_random_string(8)}.{extension}"
        else:
            name = f"{tempdir}{get_random_string(8)}"
        if not is_named_used(name):
            return name


def get_random_string(length):
    return ''.join(random.choice(string.ascii_letters) for _ in range(length))


def is_named_used(name):
    return os.path.exists(name)