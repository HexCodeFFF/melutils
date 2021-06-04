import typing

import aiosqlite
import discord
from discord.ext import commands
from datetime import datetime, timezone

botcopy = commands.Bot


class ModLogInitCog(commands.Cog):
    def __init__(self, bot):
        global botcopy
        botcopy = bot
        self.bot = bot


async def modlog(msg: str, guildid: int, userid: typing.Union[int, None] = None, modid: typing.Union[int, None] = None):
    async with aiosqlite.connect("database.sqlite") as db:
        await db.execute("INSERT INTO modlog(guild,user,moderator,text,datetime) VALUES (?,?,?,?,?)",
                         (guildid, userid, modid, msg, datetime.now(tz=timezone.utc).timestamp()))
        await db.commit()
        async with db.execute("SELECT log_channel FROM server_config WHERE guild=?", (guildid,)) as cur:
            modlogchannel = await cur.fetchone()
    if modlogchannel is None or modlogchannel[0] is None:
        return
    modlogchannel = modlogchannel[0]
    channel = await botcopy.fetch_channel(modlogchannel)
    await channel.send("**[ModLog]** " + msg, allowed_mentions=discord.AllowedMentions.none())
