import asyncio
import functools
import io
import random
import typing

import aiohttp
import discord
import twitter
from PIL import Image
from discord.ext import commands

import config
from clogs import logger


def run_in_executor(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: f(*args, **kwargs))

    return inner


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


async def resize_url(url: str) -> typing.Optional[bytes]:
    logger.debug(f"trying {url}")
    try:
        urlbytes = await saveurl(url)
        image: Image.Image = Image.open(io.BytesIO(urlbytes))
        image = image.resize((1920, 1080), Image.BICUBIC)
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue()
    except Exception as e:
        logger.error(e, exc_info=(type(e), e, e.__traceback__))
        return None


class FunnyBanner(commands.Cog, name="Funny Banner"):
    """
    send an image from @awesomepapers or set it as a banner
    """

    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.api = twitter.Api(
            consumer_key=config.twitter_api_key,
            consumer_secret=config.twitter_api_secret,
            access_token_key=config.twitter_api_access_token,
            access_token_secret=config.twitter_api_access_secret
        )

    @run_in_executor
    def get_tweets(self, screen_name=None):
        timeline = self.api.GetUserTimeline(screen_name=screen_name, count=200)
        earliest_tweet = min(timeline, key=lambda x: x.id).id

        while True:
            tweets = self.api.GetUserTimeline(
                screen_name=screen_name, max_id=earliest_tweet, count=200
            )
            new_earliest = min(tweets, key=lambda x: x.id).id

            if not tweets or new_earliest == earliest_tweet:
                break
            else:
                earliest_tweet = new_earliest
                timeline += tweets

        return timeline

    async def get_random_media_from_user(self, user):
        tweets = await self.get_tweets(user)
        while True:
            tweet = random.choice(tweets)
            if tweet.media is not None:
                if tweet.media[0].type == "photo":
                    return tweet.media[0].media_url_https

    @commands.command()
    async def awesomepaper(self, ctx):
        """
        Sends a random image from @awesomepapers on twitter.
        :returns: the image
        """
        async with ctx.typing():
            await ctx.reply(await self.get_random_media_from_user("awesomepapers"))

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_guild=True)
    async def awesomebanner(self, ctx):
        """
        sets the guild banner to a random image from @awesomepapers on twitter
        """
        async with ctx.typing():
            if "BANNER" not in ctx.guild.features:
                await ctx.reply("Guild does not support banners.")
                return
            banner_url = await self.get_random_media_from_user("awesomepapers")
            async with aiohttp.ClientSession(headers={'Connection': 'keep-alive'}) as session:
                async with session.get(banner_url) as resp:
                    if resp.status == 200:
                        url_bytes = await resp.read()
                    else:
                        raise Exception(f"status {resp.status}")
            await ctx.guild.edit(banner=bytes(url_bytes))
            await ctx.reply(f"✔️ Set guild banner to {banner_url}")

    @staticmethod
    def msgscore(msg: discord.Message):
        upvote_reactions = discord.utils.get(msg.reactions, emoji__id=830090068961656852)
        downvote_reactions = discord.utils.get(msg.reactions, emoji__id=830090093788004352)
        score = (0 if upvote_reactions is None else upvote_reactions.count) - \
                (0 if downvote_reactions is None else downvote_reactions.count)
        # msgscore is used as a sorting function. the negative timestamp means that for duplicate scores itll choose
        # the highest of the second key, which for negative datetime, will be the oldest.
        return score, msg.created_at.timestamp() * -1

    # command here
    @commands.command()
    @commands.is_owner()
    async def topbanner(self, ctx: commands.Context, preview: bool = False):
        async with ctx.typing():
            server = self.bot.get_guild(829973626442088468)
            channel = server.get_channel(908859472288551015)
            # upvote = discord.utils.get(server.emojis, id=830090068961656852)
            # downvote = discord.utils.get(server.emojis, id=830090093788004352)
            resizedimage = None
            bannermessage = None
            # go through every message in the channel in decreasing order of calculated score
            msgs = await channel.history(limit=None).flatten()
            if not msgs:
                await ctx.reply("No messages in configured channel!")
                return
            msgs.sort(key=self.msgscore, reverse=True)
            for msg in msgs:
                msgscore = self.msgscore(msg)[0]
                if msgscore <= 0:
                    continue
                # go through every attachment and embed, try to resize it to 16:9
                # if this succeeds its a valid image (errors are caught and return None), return from the loop
                if msg.attachments:
                    for att in msg.attachments:
                        resizedimage = await resize_url(att.url)
                        if resizedimage is not None:
                            break
                elif msg.embeds:
                    for embed in msg.embeds:
                        if embed.image != discord.Embed.Empty:
                            resizedimage = await resize_url(embed.image.url)
                            if resizedimage is not None:
                                break
                if resizedimage is not None:
                    bannermessage = msg
                    break
            if resizedimage is not None:  # we found a suitable banner
                if preview:
                    await ctx.reply(
                        f"{bannermessage.author.mention}'s banner will be chosen with a score of **{msgscore}**!",
                        file=discord.File(io.BytesIO(resizedimage), filename="banner.png"),
                        allowed_mentions=discord.AllowedMentions.none())
                else:
                    await server.edit(banner=resizedimage)
                    await ctx.reply(f"{bannermessage.author.mention}'s banner was chosen with a score of **{msgscore}**!",
                                    file=discord.File(io.BytesIO(resizedimage), filename="banner.png"))
                    await bannermessage.delete()


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
