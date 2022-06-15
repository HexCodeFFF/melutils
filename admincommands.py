import asyncio
import typing
from datetime import datetime, timezone

import discord
from discord.ext import commands

import scheduler
from timeconverter import time_converter


class AdminCommands(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    # fuck you, hardcoded shit for me

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.id == 187970133623308288 and member.guild.id == 827301229776207963:
            await member.add_roles(member.guild.get_role(968660002661367828))

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.guild.id == 829973626442088468:  # hos
            if len(after.roles) > len(before.roles):  # gained new roles
                if after.guild.get_role(955703823500988426) not in after.roles:  # not verified
                    await after.remove_roles(*[role for role in after.roles if role.is_assignable()])  # remove roles

    @commands.command()
    @commands.is_owner()
    async def nick(self, ctx, *, nickname):
        await ctx.guild.get_member(self.bot.user.id).edit(nick=nickname)
        await ctx.reply(f"✅ Changed nickname to `{nickname}`")

    @commands.command(aliases=["shutdown", "stop", "murder", "death", "kill"])
    @commands.is_owner()
    async def die(self, ctx):
        await ctx.reply("✅ Shutting down.")
        await self.bot.close()
        await self.bot.loop.shutdown_asyncgens()
        await self.bot.loop.shutdown_default_executor()
        self.bot.loop.stop()
        self.bot.loop.close()

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
    async def testschedule(self, ctx, time: time_converter):
        scheduletime = datetime.now(tz=timezone.utc) + time
        await scheduler.schedule(scheduletime, "debug", {"message": "hello world!"})

    @commands.command()
    @commands.is_owner()
    async def schedulemessage(self, ctx, time: time_converter, *, message):
        scheduletime = datetime.now(tz=timezone.utc) + time
        await scheduler.schedule(scheduletime, "message", {"channel": ctx.channel.id, "message": message})


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
