import typing

import nextcord as discord
import docstring_parser
from nextcord.ext import commands

import config


class HelpCommand(commands.Cog, name="Help Command"):
    """The Help Command, that's it"""

    def __init__(self, bot):
        self.bot = bot

    def showcog(self, cog):
        showcog = False
        # check if there are any non-hidden commands in the cog, if not, dont show it in the help menu.
        for com in cog.get_commands():
            if not com.hidden:
                showcog = True
                break
        return showcog

    @commands.command()
    async def help(self, ctx, *, inquiry: str = None):
        """
        Shows help on bot commands.

        :param ctx: discord context
        :param inquiry: the name of a command or command category. If none is provided, all categories are shown.
        :return: the help text if found
        """
        # unspecified inquiry
        if inquiry is None:
            embed = discord.Embed(title="Help", color=discord.Color(0xB565D9),
                                  description=f"Run `{config.command_prefix}help category` to list commands from "
                                              f"that category.")
            # for every cog
            for c in self.bot.cogs.values():
                # if there is 1 or more non-hidden command
                if self.showcog(c):
                    # add field for every cog
                    if not c.description:
                        c.description = "No Description."
                    embed.add_field(name=c.qualified_name, value=c.description)
            await ctx.reply(embed=embed)
        # if the command argument matches the name of any of the cogs that contain any not hidden commands
        elif inquiry.lower() in (coglist := {k.lower(): v for k, v in self.bot.cogs.items() if self.showcog(v)}):
            # get the cog found
            cog = coglist[inquiry.lower()]
            embed = discord.Embed(title=cog.qualified_name,
                                  description=cog.description + f"\nRun `{config.command_prefix}help command` for "
                                                                f"more information on a command.",
                                  color=discord.Color(0xD262BA))
            # add field with description for every command in the cog
            for cmd in sorted(cog.get_commands(), key=lambda x: x.name):
                if not cmd.hidden:
                    desc = cmd.short_doc if cmd.short_doc else "No Description."
                    embed.add_field(name=f"{config.command_prefix}{cmd.name}", value=desc)
            await ctx.reply(embed=embed)
        else:
            # for every bot command
            for bot_cmd in self.bot.commands:
                # if the name matches inquiry or alias and is not hidden
                if (bot_cmd.name == inquiry.lower() or inquiry.lower() in bot_cmd.aliases) and not bot_cmd.hidden:
                    # set cmd and continue
                    cmd: discord.ext.commands.Command = bot_cmd
                    break
            else:
                # inquiry doesnt match cog or command, not found
                await ctx.reply(
                    f"{config.emojis['warning']} `{inquiry}` is not the name of a command or a command category!")
                return  # past this assume cmd is defined
            embed = discord.Embed(title=config.command_prefix + cmd.name, description=cmd.cog_name,
                                  color=discord.Color(0xEE609C))
            # if command func has docstring
            if cmd.help:
                # parse it
                docstring = docstring_parser.parse(cmd.help)
                # format short/long descriptions or say if there is none.
                if docstring.short_description or docstring.long_description:
                    command_information = f"{f'**{docstring.short_description}**' if docstring.short_description else ''}" \
                                          f"\n{docstring.long_description if docstring.long_description else ''}"
                else:
                    command_information = "This command has no information."
                embed.add_field(name="Command Information", value=command_information, inline=False)

                paramtext = []
                flagcommand = False
                # for every "clean paramater" (no self or ctx)
                for param in cmd.clean_params.values():
                    def addparam(paramname, paramdefault=None, flagparam=False):
                        # get command description from docstring
                        paramhelp = discord.utils.get(docstring.params, arg_name=paramname)
                        # not found in docstring
                        if paramhelp is None:
                            paramtext.append(f"**{paramname}** - 'No description'")
                        else:
                            # optional argument (param has a default value)
                            if paramdefault:
                                pend = f" (optional, defaults to `{paramdefault}`)"
                            elif flagparam:
                                pend = f" (optional)"
                            else:
                                pend = ""
                            # format and add to paramtext list
                            paramtext.append(f"**{paramname}** - "
                                             f"{paramhelp.description if paramhelp.description else 'No description'}"
                                             f"{pend}")

                    if hasattr(param.annotation, "get_flags"):
                        flagcommand = True
                        # if command arg is flag converter, list all flag arguments
                        for name, val in param.annotation.get_flags().items():
                            addparam(name, val.default, True)
                    else:
                        # otherwise, just do it normally
                        addparam(param.name, param.default != param.empty)
                # if there are params found
                if len(paramtext):
                    # join list and add to help
                    embed.add_field(name="Parameters", value="\n".join(paramtext), inline=False)
                # add warning about flag command
                if flagcommand:
                    embed.add_field(name="Flag Syntax", value="This command uses **flag syntax**. To specify a "
                                                              "param, type `paramname: paramcontent`\nFor example, "
                                                              "if you wanted to specify `limit` as `10`, "
                                                              "you would run `m.examplecommand limit: 10`.",
                                    inline=False)
                if docstring.returns:
                    embed.add_field(name="Returns", value=docstring.returns.description, inline=False)
            else:
                # if no docstring
                embed.add_field(name="Command Information", value="This command has no information.", inline=False)
            # cmd.signature is a human readable list of args formatted like the manual usage
            embed.add_field(name="Usage", value=config.command_prefix + cmd.name + " " + cmd.signature)
            # if aliases, add
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join([config.command_prefix + a for a in cmd.aliases]))

            await ctx.reply(embed=embed)


'''
Steps to convert:
@self.bot.command() -> @commands.command()
@self.bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
self.bot -> self.self.bot
'''
