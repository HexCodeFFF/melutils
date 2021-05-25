import datetime
import difflib
import io
import traceback

import discord
from discord.ext import commands

import config
from clogs import logger
from tempfiles import TempFileSession, temp_file


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
        errorstring = discord.utils.escape_mentions(discord.utils.escape_markdown(str(commanderror)))
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
            msg = ctx.message.content
            cmd = discord.utils.escape_mentions(msg.split(' ')[0])
            allcmds = []
            for botcom in self.bot.commands:
                if not botcom.hidden:
                    allcmds.append(botcom.name)
                    allcmds += botcom.aliases
            match = difflib.get_close_matches(cmd.replace(config.command_prefix, "", 1), allcmds, n=1, cutoff=0)[0]
            err = f"{config.emojis['exclamation_question']} Command `{cmd}` does not exist. " \
                  f"Did you mean **{config.command_prefix}{match}**?"
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.NotOwner):
            err = f"{config.emojis['x']} You are not authorized to use this command."
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.CommandOnCooldown):
            err = f"{config.emojis['clock']} {errorstring}"
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.MissingRequiredArgument):
            err = f"{config.emojis['question']} {errorstring}"
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.BadArgument):
            err = f"{config.emojis['warning']} Wrong argument type. {errorstring}"
            logger.warning(err)
            await ctx.reply(err)
        elif isinstance(commanderror, discord.ext.commands.errors.CheckFailure):
            err = f"{config.emojis['x']} {errorstring}"
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
            # with open(tr, "w+", encoding="UTF-8") as t:

            with io.BytesIO() as buf:
                buf.write(bytes(trheader + ''.join(
                    traceback.format_exception(etype=type(commanderror), value=commanderror,
                                               tb=commanderror.__traceback__)), encoding='utf8'))
                buf.seek(0)
                await ctx.reply(
                    f"{config.emojis['2exclamation']} `{self.get_full_class_name(commanderror)}: {errorstring}`",
                    file=discord.File(buf, filename="traceback.txt"))  # , embed=embed)


'''
Steps to convert:
@bot.command() -> @commands.command()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
