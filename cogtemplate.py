from discord.ext import commands


class PogCog(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot

    # command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx, ...): -> function(self, ctx, ...)
bot -> self.bot
'''
