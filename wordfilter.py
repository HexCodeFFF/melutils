from discord.ext import commands


class WordFilterCog(commands.Cog, name="Word Filter"):
    """
    Moderation commands for auto-deleting certain words.
    """
    def __init__(self, bot):
        self.bot = bot

    # command here


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
