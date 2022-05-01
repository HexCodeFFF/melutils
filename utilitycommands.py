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

import aiofiles
import aiohttp
import discord
import humanize
from discord.ext import commands
from discord.ext.commands import PartialEmojiConversionFailure
from discord.ext.commands.cooldowns import BucketType
from faker import Faker

import config
import modlog
import scheduler
from clogs import logger
from timeconverter import time_converter


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


def slice_per(l, n):
    return [l[i:i + n] for i in range(0, len(l), n)]


async def url_to_dfile(url: str, name: str) -> discord.File:
    buf = io.BytesIO()
    buf.write(await saveurl(url))
    buf.seek(0)
    return discord.File(buf, filename=name + "." + url.split(".")[-1])


def all_emojis_from_content(content: str) -> typing.List[discord.PartialEmoji]:
    emojos = []
    for ematch in re.finditer(discord.PartialEmoji._CUSTOM_EMOJI_RE, content):
        try:
            emojos.append(discord.PartialEmoji.from_str(ematch.group(0)))
        except Exception as e:
            print(e)
    return emojos


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

    class AdvancedPurgeSettings(commands.FlagConverter, case_insensitive=True):
        limit: typing.Optional[int] = 100
        before: typing.Optional[typing.Union[discord.Object, datetime]] = None
        after: typing.Optional[typing.Union[discord.Object, datetime]] = None
        around: typing.Optional[typing.Union[discord.Object, datetime]] = None
        include: typing.Tuple[discord.User, ...] = None
        exclude: typing.Tuple[discord.User, ...] = None
        oldest_first: typing.Optional[bool] = None
        clean: bool = True

    @commands.command(aliases=["apurge", "advpurge", "adp", "apg"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def advancedpurge(self, ctx, *, opts: AdvancedPurgeSettings):
        """
        like m.purge but with more options

        :param limit: The number of messages to search through. This is not the number of messages that will be deleted, though it can be.
        :param before: Delete messages before this date or message.
        :param after: Delete messages after this date or message.
        :param around: Delete messages around this date or message. When using this argument, the maximum limit is 101.
        :param include: One or more members to delete messages from as a whitelist. Incompatible with `exclude`.
        :param exclude: One or more members to not delete messages from as a blacklist. Incompatible with `include`.
        :param oldest_first: If set to True, delete messages in oldest->newest order. Defaults to True if after is specified, otherwise False.
        :param clean: Deletes the invoking command before purging and purge success command after 10 seconds.
        """

        def inclfunc(m):
            return m.author in opts.include

        def exclfunc(m):
            return m.author not in opts.exclude

        check = None
        if opts.include and opts.exclude:
            raise commands.errors.UserInputError("Include and Exclude cannot both be specified.")
        if opts.include:
            check = inclfunc
        if opts.exclude:
            check = exclfunc
        pargs = {}
        if check:
            pargs['check'] = check
        for flag, value in opts:
            if flag not in ["include", "exclude", "clean_purge"] and value:
                pargs[flag] = value
        if opts.clean:
            await ctx.message.delete()
        deleted = await ctx.channel.purge(**pargs)
        msg = f"{config.emojis['check']}Deleted `{len(deleted)}` message{'' if len(deleted) == 1 else 's'}!"
        if opts.clean:
            await ctx.send(msg, delete_after=10)
        else:
            await ctx.reply(msg)
        await modlog.modlog(f"{ctx.author.mention} (`{ctx.author}`) purged {len(deleted)} message(s) from "
                            f"{ctx.channel.mention}", ctx.guild.id, modid=ctx.author.id)

    class SelectiveCloneSettings(commands.FlagConverter, case_insensitive=True):
        limit: typing.Optional[int] = None
        before: typing.Optional[typing.Union[discord.Object, datetime]] = None
        after: typing.Optional[typing.Union[discord.Object, datetime]] = None
        channel: typing.Optional[typing.Union[discord.TextChannel, discord.Thread]] = None

    @commands.command()
    @commands.has_permissions(manage_messages=True, create_public_threads=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True, create_public_threads=True)
    async def selectiveclone(self, ctx: commands.Context, *, opts: SelectiveCloneSettings):
        """
        Clone some messages from a channel into another and then delete the original messages.

        :param before: Retrieve messages before this date or message.
        :param after: Retrieve messages after this date or message.
        :param limit: The (maximum) number of messages to retrieve.
        :param channel: The channel to clone the messages into. If unspecified, will create thread on current channel.
        """
        # set target and destination
        target = ctx.channel
        destination = opts.channel
        if not destination:
            if isinstance(target, discord.Thread):
                raise commands.errors.UserInputError("Cannot create thread on current channel. Specify a channel.")
            else:
                destination = await target.create_thread(name=f"Selective Clone from #{target.name}",
                                                         type=discord.ChannelType.public_thread)
        if opts.before is None:
            opts.before = ctx.message
        to_delete = []
        async with ctx.channel.typing():
            # clone into target
            count = 0
            async for msg in target.history(limit=opts.limit, before=opts.before, after=opts.after, oldest_first=True):
                try:
                    embed = discord.Embed()
                    embed.set_author(name=msg.author.display_name, icon_url=msg.author.avatar.url)
                    embed.timestamp = msg.created_at
                    embed.description = msg.content or "`NO CONTENT`"
                    if msg.reference:
                        if msg.reference.resolved:
                            embed.add_field(name=f"Replying to *{msg.reference.resolved.author.display_name}*",
                                            value=msg.reference.resolved.content or "`NO CONTENT`")
                    # attachments
                    filecoros = [att.to_file() for att in msg.attachments] + \
                                [url_to_dfile(sticker.url, sticker.name) for sticker in msg.stickers] + \
                                [url_to_dfile(em.url, em.name) for em in all_emojis_from_content(msg.content)]
                    await destination.send(embeds=[embed] + msg.embeds, files=await asyncio.gather(*filecoros))
                    count += 1
                except Exception as e:
                    await destination.send(f"Failed to clone message {msg.id}\n```{e}```")
                    logger.error(f"Failed to clone message {msg.id}")
                    logger.error(e, exc_info=(type(e), e, e.__traceback__))
                to_delete.append(msg)
            # delete them
            single_delete = []
            bulk_delete = []
            # taken from .purge, can directly compare the ID if its safe to bulk delete (less than 14 days old)
            minimum_time = int((time.time() - 14 * 24 * 60 * 60) * 1000.0 - 1420070400000) << 22
            for msg in to_delete:
                if msg.id < minimum_time:
                    single_delete.append(msg)
                else:
                    bulk_delete.append(msg)
            # await the deletes all at once frfr
            await asyncio.wait([msg.delete() for msg in single_delete] +
                               [target.delete_messages(msgs) for msgs in slice_per(bulk_delete, 100)])
            await ctx.reply(f"Cloned {count} message{'' if count == 1 else 's'} into {destination.mention}")

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
    async def reminder(self, ctx, when: time_converter, *, reminder):
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
                             ),
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
                             ),
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

    @staticmethod
    def votes(msg: discord.Message):
        votes = discord.utils.find(lambda x: x.emoji == '✅', msg.reactions)
        return 0 if votes is None else votes.count

    @commands.command(hidden=True)
    @commands.is_owner()
    async def countvotes(self, ctx: commands.Context):
        await ctx.message.delete()
        msgs = [msg async for msg in ctx.history(limit=None)]
        if not msgs:
            await ctx.reply("No messages in channel")
            return
        msgs.sort(key=self.votes, reverse=True)

        async with aiofiles.open("votetemplate.html", "r") as f:
            template = await f.read()

        out = ""
        for msg in msgs:
            votes = self.votes(msg) - 1
            if msg.stickers:
                sticker = msg.stickers[0]
                name = sticker.name
                url = sticker.url
            else:
                try:
                    emoj = await commands.PartialEmojiConverter().convert(ctx, msg.content)
                except commands.PartialEmojiConversionFailure:
                    continue
                name = emoj.name
                url = emoj.url
            out += f"""
            <tr>
                <td><img src="{url}" alt="{name}" height="32"></td>
                <td>{name}</td>
                <td>{votes}</td>
            </tr>
            """
        out = template.replace("REPLACEME", out)
        with io.BytesIO() as buf:
            buf.write(bytes(out, encoding='utf8'))
            buf.seek(0)
            await ctx.author.send(file=discord.File(buf, filename="out.html"))

    @commands.command()
    @commands.bot_has_guild_permissions(manage_emojis=True)
    @commands.has_guild_permissions(manage_emojis=True)
    async def removeemoji(self, ctx: commands.Context, *, emoji: discord.Emoji):
        assert emoji.guild == ctx.guild
        await emoji.delete()
        await ctx.reply("✔️ emoji deleted")

    @commands.command()
    @commands.bot_has_guild_permissions(manage_emojis=True)
    @commands.has_guild_permissions(manage_emojis=True)
    async def removesticker(self, ctx: commands.Context, *, sticker: discord.GuildSticker):
        assert sticker.guild == ctx.guild
        await sticker.delete()
        await ctx.reply("✔️ sticker deleted")

    @commands.command()
    async def id(self, ctx: commands.Context,
                 obj: typing.Union[discord.abc.GuildChannel, discord.User, discord.Guild,
                                   discord.Thread, discord.PartialEmoji, discord.Role,
                                   discord.Object] = None):
        """
        gets the ID of a discord object
        :param ctx: discord context
        :param obj: a user, emoji, channel, guild, or role. will default to the author if not specified
        :return: the ID of the object.
        """
        if obj is None:
            obj = ctx.author
        if hasattr(obj, "mention"):
            await ctx.reply(f"{obj.mention}'s ID is `{obj.id}`", )
        else:
            await ctx.reply(f"{str(obj)}'s ID is `{obj.id}`", )

    @commands.command()
    async def doxx(self, ctx: commands.Context, user: typing.Optional[discord.User] = None):
        """
        generate a **completely fake** block of details based off a user.
        :param ctx:
        :param user: the user to seed the generation. using the command on this user twice will yield the same info.
            if command is in reply to a message, message author can be used if user is unspecified.
        """
        faker = Faker()
        if not user and ctx.message.reference:
            user = ctx.message.reference.resolved.author
        if user:
            faker.seed_instance(user.id)
        credit_card = " ".join(slice_per(faker.credit_card_number("visa16"), 4))
        meme = ["That's a nice argument. Unfortunately,",
                f"{faker.address()}",
                f"{', '.join(faker.location_on_land(coords_only=True))}",
                f"{faker.ipv4_public()} {faker.ipv6()}",
                f"{faker.ssn()}",
                f"{credit_card}, {faker.credit_card_expire()}, {faker.credit_card_security_code('visa16')}"
                ]
        await ctx.reply("\n".join(meme))


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
