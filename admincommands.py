import asyncio

import discord
from discord.ext import commands


class AdminCommands(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.is_owner()
    async def nick(self, ctx, *, nickname="gay ass doge"):
        await ctx.guild.get_member(self.bot.user.id).edit(nick=nickname)
        await ctx.reply(f"✅ Changed nickname to `{nickname}`")

    @commands.command(aliases=["shutdown", "stop"])
    @commands.is_owner()
    async def die(self, ctx):
        await ctx.reply("✅ Shutting down.")
        await self.bot.close()

    @commands.command()
    @commands.is_owner()
    async def sayhere(self, ctx, *, msg):
        if ctx.me.permissions_in(ctx.channel).manage_messages:
            asyncio.create_task(ctx.message.delete())
        asyncio.create_task(ctx.channel.send(msg))

    @commands.command()
    @commands.is_owner()
    async def say(self, ctx, channelid: discord.TextChannel, *, msg):
        channel = self.bot.get_channel(channelid)
        if ctx.me.permissions_in(channel).manage_messages:
            asyncio.create_task(ctx.message.delete())
        asyncio.create_task(channel.send(msg))


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
