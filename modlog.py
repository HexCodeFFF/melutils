import typing
from datetime import datetime, timezone

import aiosqlite
import discord
from discord.ext import commands

botcopy = commands.Bot


class ModLogInitCog(commands.Cog):
    def __init__(self, bot):
        global botcopy
        botcopy = bot
        self.bot = bot


async def modlog(msg: str, guildid: int, userid: typing.Optional[int] = None, modid: typing.Optional[int] = None,
                 db: typing.Optional[aiosqlite.Connection] = None):
    passeddb = db is not None
    if not passeddb:  # if not passed DB conn, make new one. nested db connections have issues commiting.
        db = await aiosqlite.connect("database.sqlite")
    await db.execute("INSERT INTO modlog(guild,user,moderator,text,datetime) VALUES (?,?,?,?,?)",
                     (guildid, userid, modid, msg, datetime.now(tz=timezone.utc).timestamp()))
    await db.commit()
    async with db.execute("SELECT log_channel,bulk_log_channel FROM server_config WHERE guild=?", (guildid,)) as cur:
        modlogchannel = await cur.fetchone()
    if not passeddb:
        await db.close()
    if modlogchannel is None or modlogchannel[0] is None:
        return
    for ch in modlogchannel:  # send to normal and bulk
        channel = await botcopy.fetch_channel(ch)
        await channel.send("**[ModLog]** " + msg, allowed_mentions=discord.AllowedMentions.none())
