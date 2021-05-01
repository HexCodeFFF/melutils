import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType


class UtilityCommands(commands.Cog, name="Utility"):
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


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
