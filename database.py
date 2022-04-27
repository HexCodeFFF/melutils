import typing

import aiosqlite

db: typing.Optional[aiosqlite.Connection] = None


async def create_db():
    global db
    db = await aiosqlite.connect("database.sqlite")
    return db
