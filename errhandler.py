import datetime
import traceback
import config
from tempfiles import temp_file, TempFileSession
import discord
from discord.ext import commands
from clogs import logger


class ErrorHandler(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    # command here
    def get_full_class_name(self, obj):
        module = obj.__class__.__module__
        if module is None or module == str.__class__.__module__:
            return obj.__class__.__name__
        return module + '.' + obj.__class__.__name__

    @commands.Cog.listener()
    async def on_command_error(self, ctx, commanderror):
        if isinstance(commanderror, discord.Forbidden):
            if not ctx.me.permissions_in(ctx.channel).send_messages:
                if ctx.me.permissions_in(ctx.author).send_messages:
                    err = f"{config.emojis['x']} I don't have permissions to send messages in that channel."
                    await ctx.author.send(err)
                    logger.warning(err)
                    return
                else:
                    logger.warning("No permissions to send in command channel or to DM author.")
        if isinstance(commanderror, discord.ext.commands.errors.CommandNotFound):
            msg = ctx.message.content.replace("@", "\\@")
            err = f"{config.emojis['exclamation_question']} Command `{msg.split(' ')[0]}` does not exist."
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.NotOwner):
            err = f"{config.emojis['x']} You are not authorized to use this command."
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.CommandOnCooldown):
            err = f"{config.emojis['clock']} " + str(commanderror).replace("@", "\\@")
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.MissingRequiredArgument):
            err = f"{config.emojis['question']} " + str(commanderror).replace("@", "\\@")
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.BadArgument):
            err = f"{config.emojis['warning']} Bad Argument! Did you put text where a number should be? `" + \
                  str(commanderror).replace("@", "\\@") + "`"
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.CheckFailure):
            err = f"{config.emojis['x']} " + str(commanderror).replace("@", "\\@")
            logger.warning(err)
            await ctx.reply(err)
        # elif isinstance(commanderror, discord.ext.commands.errors.CommandInvokeError) and \
        #         isinstance(commanderror.original, improcessing.NonBugError):
        #    await ctx.reply(f"{config.emojis['2exclamation']}" + str(commanderror.original)[:1000].replace("@", "\\@"))
        else:
            if isinstance(commanderror, discord.ext.commands.errors.CommandInvokeError):
                commanderror = commanderror.original
            logger.error(commanderror, exc_info=(type(commanderror), commanderror, commanderror.__traceback__))
            # with TempFileSession() as tempfilesession:
            tr = temp_file("txt")
            trheader = f"DATETIME:{datetime.datetime.now()}\nCOMMAND:{ctx.message.content}\nTRACEBACK:\n"
            with open(tr, "w+", encoding="UTF-8") as t:
                t.write(trheader + ''.join(
                    traceback.format_exception(etype=type(commanderror), value=commanderror,
                                               tb=commanderror.__traceback__)))
            embed = discord.Embed(color=0xed1c24,
                                  description="uh oh fucky wucky!!")
            # embed.add_field(name=f"{config.emojis['2exclamation']} Report Issue to GitHub",
            #                 value=f"[Create New Issue](https://github.com/HexCodeFFF/captionbot"
            #                       f"/issues/new?labels=bug&template=bug_report.md&title"
            #                       f"={urllib.parse.quote(str(commanderror)[:128], safe='')})\n[View Issu"
            #                       f"es](https://github.com/HexCodeFFF/captionbot/issues)")
            await ctx.reply(f"{config.emojis['2exclamation']} `{self.get_full_class_name(commanderror)}: " +
                            str(commanderror)[:128].replace("@", "\\@") + "`",
                            file=discord.File(tr))  # , embed=embed)


'''
Steps to convert:
@bot.command() -> @commands.command()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
