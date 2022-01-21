import asyncio
import typing

import aiosqlite
import nextcord as discord
from nextcord.ext import commands

db: typing.Optional[aiosqlite.Connection] = None


async def create_db():
    global db
    db = await aiosqlite.connect("database.sqlite")


class InitDB(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        bot.loop.run_until_complete(create_db())
