import glob
import os
import config
from clogs import logger
import discord
from discord.ext import commands
import database

from errhandler import ErrorHandler
from helpcommand import HelpCommand
from funcommands import FunCommands
from admincommands import AdminCommands

if not os.path.exists(config.temp_dir.rstrip("/")):
    os.mkdir(config.temp_dir.rstrip("/"))
for f in glob.glob(f'{config.temp_dir}*'):
    os.remove(f)

bot = commands.Bot(command_prefix=config.command_prefix, help_command=None, case_insensitive=True)
bot.add_cog(ErrorHandler(bot))
bot.add_cog(HelpCommand(bot))
bot.add_cog(FunCommands(bot))
bot.add_cog(AdminCommands(bot))


def logcommand(cmd):
    cmd = cmd.replace("\n", "\\n")
    if len(cmd) > 100:
        cmd = cmd[:100] + "..."
    return cmd


@bot.listen()
async def on_command(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        logger.log(25,
                   f"@{ctx.message.author.name}#{ctx.message.author.discriminator} ran "
                   f"'{logcommand(ctx.message.content)}' in DMs")
    else:
        logger.log(25,
                   f"@{ctx.message.author.name}#{ctx.message.author.discriminator}"
                   f" ({ctx.message.author.display_name}) ran '{logcommand(ctx.message.content)}' in channel "
                   f"#{ctx.channel.name} in server {ctx.guild}")


@bot.listen()
async def on_command_completion(ctx):
    logger.log(35,
               f"Command '{logcommand(ctx.message.content)}' by @{ctx.message.author.name}#{ctx.message.author.discriminator} "
               f"is complete!")


@bot.event
async def on_ready():
    logger.log(35, f"Logged in as {bot.user.name}!")
    game = discord.Activity(name=f"with my balls | {config.command_prefix}help", type=discord.ActivityType.playing)
    await bot.change_presence(activity=game)


bot.run(config.bot_token)
