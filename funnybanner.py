import asyncio
import functools
import io
import random
import typing

import PIL.GifImagePlugin
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


def extract_and_resize_frames(im: PIL.GifImagePlugin.GifImageFile, resize_to):
    """
    Iterate the GIF, extracting each frame and resizing them

    Returns:
        An array of all frames
    """

    """
    Pre-process pass over the image to determine the mode (full or additive).
    Necessary as assessing single frames isn't reliable. Need to know the mode
    before processing all frames.
    """
    mode = "full"
    try:
        while True:
            if im.tile:
                tile = im.tile[0]
                update_region = tile[1]
                update_region_dimensions = update_region[2:]
                if update_region_dimensions != im.size:
                    mode = 'partial'
                    break
            im.seek(im.tell() + 1)
    except EOFError:
        pass

    im.seek(0)

    i = 0
    p = im.getpalette()
    last_frame = im.convert('RGBA')

    all_frames = []

    try:
        while True:
            # print("saving %s (%s) frame %d, %s %s" % (path, mode, i, im.size, im.tile))

            '''
            If the GIF uses local colour tables, each frame will have its own palette.
            If not, we need to apply the global palette to the new frame.
            '''
            try:
                if not im.getpalette():
                    im.putpalette(p)
            except ValueError:
                pass

            new_frame = Image.new('RGBA', im.size)

            '''
            Is this file a "partial"-mode GIF where frames update a region of a different size to the entire image?
            If so, we need to construct the new frame by pasting it on top of the preceding frames.
            '''
            if mode == 'partial':
                new_frame.paste(last_frame)

            new_frame.paste(im, (0, 0), im.convert('RGBA'))

            all_frames.append(new_frame.resize(resize_to, Image.BICUBIC))

            i += 1
            last_frame = new_frame
            im.seek(im.tell() + 1)
    except EOFError:
        pass

    return all_frames


def resize_gif(im: Image.Image, save_as, resize_to):
    """
    Resizes the GIF to a given length:

    Args:
        im: file
        save_as (optional): Path of the resized gif. If not set, the original gif will be overwritten.
        resize_to (optional): new size of the gif. Format: (int, int). If not set, the original GIF will be resized to
                              half of its size.
    """
    all_frames = extract_and_resize_frames(im, resize_to)

    if len(all_frames) == 1:
        print("Warning: only 1 frame found")
        all_frames[0].save(save_as, optimize=True, format="GIF")
    else:
        all_frames[0].save(save_as, optimize=True, save_all=True, append_images=all_frames[1:], loop=0, format="GIF",
                           duration=im.info['duration'])


async def resize_url(url: str) -> typing.Optional[typing.Tuple[bytes, typing.Literal["png", "gif"]]]:
    logger.debug(f"trying {url}")
    try:
        urlbytes = await saveurl(url)
        image: Image.Image = Image.open(io.BytesIO(urlbytes))
        anim = getattr(image, "is_animated", False)
        img_byte_arr = io.BytesIO()
        if anim:
            resize_gif(image, img_byte_arr, (192, 108))
        else:
            image = image.resize((1920, 1080), Image.BICUBIC)
            image.save(img_byte_arr, format='PNG')
        return img_byte_arr.getvalue(), "gif" if anim else "png"
    except Exception as e:
        logger.error(e, exc_info=(type(e), e, e.__traceback__))
        return None


class FunnyBanner(commands.Cog, name="Funny Banner"):
    """
    send an image from @Amazingpapers or set it as a banner
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
        Sends a random image from @Amazingpapers on twitter.
        :returns: the image
        """
        async with ctx.typing():
            await ctx.reply(await self.get_random_media_from_user("Amazingpapers"))

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.bot_has_guild_permissions(manage_guild=True)
    async def awesomebanner(self, ctx):
        """
        sets the guild banner to a random image from @Amazingpapers on twitter
        """
        async with ctx.typing():
            if "BANNER" not in ctx.guild.features:
                await ctx.reply("Guild does not support banners.")
                return
            banner_url = await self.get_random_media_from_user("Amazingpapers")
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
        # discord.utils.get errors if objetc doesnt have attr (some reactions arent emoji objects but unicode str)
        upvote_reactions = discord.utils.find(lambda x: hasattr(x.emoji, "id") and x.emoji.id == 830090068961656852,
                                              msg.reactions)
        downvote_reactions = discord.utils.find(lambda x: hasattr(x.emoji, "id") and x.emoji.id == 830090093788004352,
                                                msg.reactions)
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
            msgs = [message async for message in channel.history(limit=None)]
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
                        if embed.image:
                            resizedimage = await resize_url(embed.image.url)
                            if resizedimage is not None:
                                break
                        elif embed.url and embed.type in ["image", "gifv"]:
                            if embed.video:
                                resizedimage = await resize_url(embed.video.url)
                                if resizedimage is not None:
                                    break
                            resizedimage = await resize_url(embed.url)
                            if resizedimage is not None:
                                break
                if resizedimage is not None:
                    bannermessage = msg
                    break
            if resizedimage is not None:  # we found a suitable banner
                resizedimage, ext = resizedimage
                if preview:
                    await ctx.reply(
                        f"{bannermessage.author.mention}'s banner will be chosen with a score of **{msgscore}**!",
                        file=discord.File(io.BytesIO(resizedimage), filename=f"banner.{ext}"),
                    )
                else:
                    await server.edit(banner=resizedimage)
                    await ctx.reply(
                        f"{bannermessage.author.mention}'s banner was chosen with a score of **{msgscore}**!",
                        file=discord.File(io.BytesIO(resizedimage), filename=f"banner.{ext}"),
                        allowed_mentions=discord.AllowedMentions(everyone=False, users=True, roles=False,
                                                                 replied_user=True))
                    await bannermessage.delete()

    @commands.command()
    @commands.is_owner()
    async def resizeurl(self, ctx: commands.Context, url: str):
        await ctx.reply(file=discord.File(io.BytesIO(await resize_url(url)), filename="url.gif"))


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
