import discord
from discord.ext import commands


class ThreadUtilsCog(commands.Cog, name="Thread Utils"):
    """
    Convenience commands for quickly managing threads.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_guild_permissions(manage_threads=True)
    @commands.bot_has_guild_permissions(manage_threads=True)
    async def lockthread(self, ctx: commands.Context, thread: discord.Thread = None):
        """
        locks a thread (archives it and only allows moderators to unarchive it)
        :param ctx: discord context
        :param thread: the thread to lock. if unspecified, uses thread command was sent in.
        """
        if thread is None:
            if isinstance(ctx.channel, discord.Thread):
                thread = ctx.channel
            else:
                await ctx.reply(f"Run this command inside a thread or mention a thread.")
                return
        await ctx.reply(f"✔ Locking thread")
        await thread.edit(locked=True, archived=True)

    @commands.command(aliases=["archive"])
    @commands.has_guild_permissions(manage_threads=True)
    @commands.bot_has_guild_permissions(manage_threads=True)
    async def archivethread(self, ctx, thread: discord.Thread = None):
        """
        archives a thread (archives it and only allows moderators to unarchive it)
        :param ctx: discord context
        :param thread: the thread to archive. if unspecified, uses thread command was sent in.
        """
        if thread is None:
            if isinstance(ctx.channel, discord.Thread):
                thread = ctx.channel
            else:
                await ctx.reply(f"Run this command inside a thread or mention a thread.")
                return
        await thread.edit(archived=True)


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
