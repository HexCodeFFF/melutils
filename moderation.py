import discord
from discord.ext import commands
import typing
from timeconverter import TimeConverter
from clogs import logger


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def warn(self, ctx, user: discord.Member, warn_length: typing.Optional[TimeConverter] = 604800, *,
                   reason="No reason provided."):
        await ctx.reply(f"user: {user}, warn length: {warn_length}, reason: {reason}")
    # command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
