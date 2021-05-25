import glob
import os
import config
from clogs import logger
import discord
from discord.ext import commands
import scheduler
from errhandler import ErrorHandler
from funnybanner import FunnyBanner
from helpcommand import HelpCommand
from funcommands import FunCommands
from admincommands import AdminCommands
from macro import MacroCog
from modlog import ModLogInitCog
from utilitycommands import UtilityCommands
from moderation import ModerationCog

if not os.path.exists(config.temp_dir.rstrip("/")):
    os.mkdir(config.temp_dir.rstrip("/"))
for f in glob.glob(f'{config.temp_dir}*'):
    os.remove(f)

intents = discord.Intents.default()
intents.members = True
activity = discord.Activity(name=f"with my balls | {config.command_prefix}help", type=discord.ActivityType.playing)
bot = commands.Bot(command_prefix=config.command_prefix, help_command=None, case_insensitive=True, activity=activity,
                   intents=intents)
bot.add_cog(ErrorHandler(bot))
bot.add_cog(HelpCommand(bot))
bot.add_cog(FunCommands(bot))
bot.add_cog(AdminCommands(bot))
bot.add_cog(UtilityCommands(bot))
bot.add_cog(ModerationCog(bot))
bot.add_cog(scheduler.ScheduleInitCog(bot))
bot.add_cog(ModLogInitCog(bot))
bot.add_cog(FunnyBanner(bot))
bot.add_cog(MacroCog(bot))


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
    scheduler.botcopy = bot
    # await scheduler.start()
    logger.log(35, f"Logged in as {bot.user.name}!")
    # game = discord.Activity(name=f"with my balls | {config.command_prefix}help", type=discord.ActivityType.playing)
    # await bot.change_presence(activity=game)


bot.run(config.bot_token)
