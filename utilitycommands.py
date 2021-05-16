import asyncio
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

import aiohttp
import discord
import humanize
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
import scheduler
from timeconverter import TimeConverter
from clogs import logger


class UtilityCommands(commands.Cog, name="Utility"):
    """
    miscellaneous utility commands
    """

    def __init__(self, bot):
        self.bot = bot

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
    @commands.command(aliases=["cw", "tw", "censor", "s", "sp"])
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
                content = f"||{discord.utils.escape_markdown(content)}||"
            if content or outattachments:
                await asyncio.gather(
                    ctx.send(content=content, files=outattachments, embed=embed),
                    ctx.message.delete()
                )
                return
            elif ctx.message.reference and ctx.author.permissions_in(ctx.channel).manage_messages:
                outattachments = []
                for att in ctx.message.reference.resolved.attachments:
                    outattachments.append(await att.to_file(spoiler=True))
                embed = discord.Embed().set_author(name=ctx.message.reference.resolved.author.display_name,
                                                   icon_url=ctx.message.reference.resolved.author.avatar_url)
                embed.set_footer(text=f"Spoilered by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)
                content = f"||{discord.utils.escape_markdown(ctx.message.reference.resolved.content)}||" \
                    if ctx.message.reference.resolved.content else ""
                await asyncio.gather(
                    ctx.send(content=content, files=outattachments, embed=embed),
                    ctx.message.delete(),
                    ctx.message.reference.resolved.delete()
                )
                return
            await ctx.reply("❌ no content to spoiler or no replied message to spoiler.")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
