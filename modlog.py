import typing
from datetime import datetime, timezone

from nextcord.ext import commands

import database

botcopy = commands.Bot


class ModLogInitCog(commands.Cog):
    def __init__(self, bot):
        global botcopy
        botcopy = bot
        self.bot = bot


async def modlog(msg: str, guildid: int, userid: typing.Optional[int] = None, modid: typing.Optional[int] = None):
    await database.db.execute("INSERT INTO modlog(guild,user,moderator,text,datetime) VALUES (?,?,?,?,?)",
                              (guildid, userid, modid, msg, datetime.now(tz=timezone.utc).timestamp()))
    await database.db.commit()
    async with database.db.execute("SELECT log_channel,bulk_log_channel FROM server_config WHERE guild=?",
                                   (guildid,)) as cur:
        modlogchannel = await cur.fetchone()
    if modlogchannel is None or modlogchannel[0] is None:
        return
    for ch in modlogchannel:  # send to normal and bulk
        channel = await botcopy.fetch_channel(ch)
        await channel.send("**[ModLog]** " + msg, )
