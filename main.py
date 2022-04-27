import glob
import itertools
import os
import sqlite3

import discord
from discord.ext import commands

import config
import database
import errhandler
import scheduler
from admincommands import AdminCommands
from autoreaction import AutoReactionCog
from birthday import BirthdayCog
from bulklog import BulkLog
from clogs import logger
from errhandler import ErrorHandler
from funcommands import FunCommands
from funnybanner import FunnyBanner
from gatekeep import GateKeep
from helpcommand import HelpCommand
from macro import MacroCog
from moderation import ModerationCog
from modlog import ModLogInitCog
from nitroroles import NitroRolesCog
from threadutils import ThreadUtilsCog
from utilitycommands import UtilityCommands
from wordsinthebible import BibleCog
from xp import ExperienceCog

if not os.path.exists(config.temp_dir.rstrip("/")):
    os.mkdir(config.temp_dir.rstrip("/"))
for f in glob.glob(f'{config.temp_dir}*'):
    os.remove(f)
# init db if not ready
logger.debug("checking db")
con = sqlite3.connect("database.sqlite")
cur = con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_master' AND name != "
                  "'sqlite_sequence'")
numoftables = cur.fetchone()[0]
if numoftables == 0:
    logger.debug("detected empty database, initializing")
    with open("makedatabase.sql", "r") as f:
        makesql = f.read()
    with con:
        con.executescript(makesql)
    logger.debug("initialized db!")
con.close()

# loop = asyncio.new_event_loop()
# loop.run_until_complete(create_db())
# loop.close()

# make copy of .reply() function
discord.Message.orig_reply = discord.Message.reply


async def safe_reply(self: discord.Message, *args, **kwargs) -> discord.Message:
    # replies to original message if it exists, just sends in channel if it doesnt
    try:
        # retrieve this message, will throw NotFound if its not found and go to the fallback option.
        # turns out trying to send a message will close any file objects which causes problems
        await self.channel.fetch_message(self.id)
        # reference copy of .reply() since this func will override .reply()
        return await self.orig_reply(*args, **kwargs)
    # for some reason doesnt throw specific error. if its unrelated httpexception itll just throw again and fall to the
    # error handler hopefully
    except (discord.errors.NotFound, discord.errors.HTTPException) as e:
        logger.debug(f"abandoning reply to {self.id} due to {errhandler.get_full_class_name(e)}, "
                     f"sending message in {self.channel.id}.")
        return await self.channel.send(*args, **kwargs)


def allcasecombinations(s):
    # https://stackoverflow.com/a/71655076/9044183
    return list({''.join(x) for x in itertools.product(*zip(s.upper(), s.lower()))})


# override .reply()
discord.Message.reply = safe_reply

intents = discord.Intents.default()
intents.members = True
activity = discord.Activity(name=f"you | {config.command_prefix}help", type=discord.ActivityType.watching)


class MyBot(commands.Bot):
    async def setup_hook(self):
        await database.create_db()
        await bot.add_cog(ErrorHandler(bot))
        await bot.add_cog(HelpCommand(bot))
        await bot.add_cog(FunCommands(bot))
        await bot.add_cog(AdminCommands(bot))
        await bot.add_cog(UtilityCommands(bot))
        await bot.add_cog(ModerationCog(bot))
        await bot.add_cog(scheduler.ScheduleInitCog(bot))
        await bot.add_cog(ModLogInitCog(bot))
        await bot.add_cog(FunnyBanner(bot))
        await bot.add_cog(MacroCog(bot))
        await bot.add_cog(AutoReactionCog(bot))
        await bot.add_cog(ThreadUtilsCog(bot))
        await bot.add_cog(BirthdayCog(bot))
        await bot.add_cog(NitroRolesCog(bot))
        await bot.add_cog(BulkLog(bot))
        await bot.add_cog(ExperienceCog(bot))
        await bot.add_cog(GateKeep(bot))
        await bot.add_cog(BibleCog(bot))
        await scheduler.start()


bot = MyBot(command_prefix=allcasecombinations(config.command_prefix), help_command=None, case_insensitive=True,
            activity=activity,
            intents=intents, allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=False,
                                                                      replied_user=True))


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
    logger.log(35, f"Logged in as {bot.user.name}!")
    guilddict = {guild.id: guild.name for guild in bot.guilds}
    logger.debug(f"{len(bot.guilds)} guild(s): {guilddict}")


@bot.is_owner
@bot.command(hidden=True)
async def leave(ctx: commands.Context, guild: discord.Guild):
    await guild.leave()
    await ctx.reply(f"Left {guild} ({guild.id})")


bot.run(config.bot_token)
