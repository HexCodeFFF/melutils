import asyncio
import functools
import io
import random

import aiohttp
import discord
from discord.ext import commands
import twitter

import config
from clogs import logger


def run_in_executor(f):
    @functools.wraps(f)
    def inner(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: f(*args, **kwargs))

    return inner


class FunnyBanner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
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
    # command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
