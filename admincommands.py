import asyncio
import typing
from datetime import datetime, timezone

import nextcord as discord
from nextcord.ext import commands

import scheduler
from timeconverter import TimeConverter


class AdminCommands(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.is_owner()
    async def nick(self, ctx, *, nickname):
        await ctx.guild.get_member(self.bot.user.id).edit(nick=nickname)
        await ctx.reply(f"✅ Changed nickname to `{nickname}`")

    @commands.command(aliases=["shutdown", "stop"])
    @commands.is_owner()
    async def die(self, ctx):
        await ctx.reply("✅ Shutting down.")
        await self.bot.close()

    @commands.command()
    @commands.is_owner()
    async def say(self, ctx, channel: typing.Optional[typing.Union[discord.TextChannel, discord.User]], *, msg):
        if not channel:
            channel = ctx.channel
        if ctx.channel.permissions_for(ctx.me).manage_messages:
            asyncio.create_task(ctx.message.delete())
        asyncio.create_task(channel.send(msg))

    @commands.command()
    @commands.is_owner()
    async def testschedule(self, ctx, time: TimeConverter):
        scheduletime = datetime.now(tz=timezone.utc) + time
        await scheduler.schedule(scheduletime, "debug", {"message": "hello world!"})

    @commands.command()
    @commands.is_owner()
    async def schedulemessage(self, ctx, time: TimeConverter, *, message):
        scheduletime = datetime.now(tz=timezone.utc) + time
        await scheduler.schedule(scheduletime, "message", {"channel": ctx.channel.id, "message": message})


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
