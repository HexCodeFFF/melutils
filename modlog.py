import aiosqlite
from discord.ext import commands
import discord

botcopy = commands.Bot


class ModLogInitCog(commands.Cog):
    def __init__(self, bot):
        global botcopy
        botcopy = bot
        self.bot = bot


async def modlog(msg: str, guildid: int):
    async with aiosqlite.connect("database.sqlite") as db:
        async with db.execute("SELECT log_channel FROM server_config WHERE guild=?", (guildid,)) as cur:
            modlogchannel = await cur.fetchone()
    if modlogchannel is None or modlogchannel[0] is None:
        return
    modlogchannel = modlogchannel[0]
    channel = await botcopy.fetch_channel(modlogchannel)
    await channel.send("**[ModLog]** " + msg, allowed_mentions=discord.AllowedMentions.none())
