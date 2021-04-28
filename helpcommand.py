import discord
from discord.ext import commands

import config


class HelpCommand(commands.Cog):
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
    async def help(self, ctx, *, arg=None):
        """
        Shows the help message.

        :Usage=$help `[inquiry]`
        :Param=inquiry - the name of a command or command category. If none is provided, all categories are shown.
        """
        if arg is None:
            embed = discord.Embed(title="Help", color=discord.Color(0xB565D9),
                                  description=f"Run `{config.command_prefix}help category` to list commands from "
                                              f"that category.")
            for c in self.bot.cogs.values():
                if self.showcog(c):
                    if not c.description:
                        c.description = "No Description."
                    embed.add_field(name=c.qualified_name, value=c.description)
            await ctx.reply(embed=embed)
        # if the command argument matches the name of any of the cogs that contain any not hidden commands
        elif arg.lower() in [c.lower() for c, v in self.bot.cogs.items() if self.showcog(v)]:
            cogs_lower = {k.lower(): v for k, v in self.bot.cogs.items()}
            cog = cogs_lower[arg.lower()]
            embed = discord.Embed(title=cog.qualified_name,
                                  description=cog.description + f"\nRun `{config.command_prefix}help command` for "
                                                                f"more information on a command.",
                                  color=discord.Color(0xD262BA))
            for cmd in sorted(cog.get_commands(), key=lambda x: x.name):
                if not cmd.hidden:
                    embed.add_field(name=f"{config.command_prefix}{cmd.name}", value=cmd.short_doc)
            await ctx.reply(embed=embed)
        # elif arg.lower() in [c.name for c in self.bot.commands]:
        else:
            for all_cmd in self.bot.commands:
                if (all_cmd.name == arg.lower() or arg.lower() in all_cmd.aliases) and not all_cmd.hidden:
                    cmd: discord.ext.commands.Command = all_cmd
                    break
            else:
                await ctx.reply(
                    f"{config.emojis['warning']} `{arg}` is not the name of a command or a command category!")
                return
            embed = discord.Embed(title=config.command_prefix + cmd.name, description=cmd.cog_name,
                                  color=discord.Color(0xEE609C))
            fields = {}
            fhelp = []
            for line in cmd.help.split("\n"):
                if line.startswith(":"):
                    if line.split("=")[0].strip(":") in fields:
                        fields[line.split("=")[0].strip(":")] += "\n" + "=".join(line.split("=")[1:])
                    else:
                        fields[line.split("=")[0].strip(":")] = "=".join(line.split("=")[1:])
                else:
                    fhelp.append(line)
            fhelp = "\n".join(fhelp)
            embed.add_field(name="Command Information", value=fhelp.replace("$", config.command_prefix),
                            inline=False)
            for k, v in fields.items():
                if k == "Param":
                    k = "Parameters"
                embed.add_field(name=k, value=v.replace("n,", config.command_prefix), inline=False)
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
