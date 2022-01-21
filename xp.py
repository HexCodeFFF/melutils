import typing

import aiosqlite
import nextcord as discord
from nextcord.ext import commands
from nextcord.ext.commands import BucketType

import moderation
from clogs import logger
import database

class ExperienceCog(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        # var and not db for performance and cause it doesnt really matter if its lost
        self.last_message_in_guild = {
            "user.guild": "datetime object"
        }
        # suspend XP gain for recalculation
        self.suspended_guild = []

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and myself (which should be a bot but lets check anyways)
        if message.author.bot or message.author == self.bot.user:
            return
        # guilds only frfr
        if not message.guild:
            return
        if message.guild.id in self.suspended_guild:
            return

        # we dont care how long the timeout is if there is no entry for last message
        if f"{message.author.id}.{message.guild.id}" in self.last_message_in_guild:
            # get timeout between message for this guild
            async with database.db.execute("SELECT time_between_xp FROM server_config WHERE guild=?",
                                  (message.guild.id,)) as cur:
                cur: aiosqlite.Cursor
                timeout = await cur.fetchone()
            # error for now
            if timeout is None:
                return
            # make sure the minimum timeout has passed
            sincelastmsg = discord.utils.utcnow() - self.last_message_in_guild[f"{message.author.id}."
                                                                               f"{message.guild.id}"]
            if sincelastmsg.total_seconds() < timeout[0]:
                logger.debug(f"{message.author} has to wait {timeout[0] - sincelastmsg.total_seconds()} before "
                             f"gaining XP again in {message.guild}.")
                return
        # check if user or channel is excluded from gaining XP
        async with database.db.execute("SELECT userorchannel FROM guild_xp_exclusions WHERE guild=?",
                              (message.guild.id,)) as cur:
            cur: aiosqlite.Cursor
            async for row in cur:
                excl = row[0]
                if message.channel.id == excl or message.author.id == excl:
                    logger.debug(f"{message.author} tried to gain XP as an excluded user or in an excluded channel"
                                 f" in {message.guild}. Exclusion is {excl}.")
                    return
        # create new record of 1 xp or update by 1
        await database.db.execute("""INSERT INTO experience(user, guild, experience) VALUES (?,?,1)
                            ON CONFLICT(user, guild) DO UPDATE SET experience = experience + 1;""",
                         (message.author.id, message.guild.id))
        await database.db.commit()
        self.last_message_in_guild[f"{message.author.id}.{message.guild.id}"] = message.created_at
        logger.debug(f"{message.author} gained XP in {message.guild}")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 60 * 60 * 24 * 7, BucketType.guild)
    async def recalculateguildxp(self, ctx: commands.Context):
        """
        recalculate guild's XP from message history
        """
        # TODO: implement
        raise NotImplementedError

    @moderation.mod_only()
    @commands.command()
    async def excludefromxp(self, ctx: commands.Context,
                            userorchannel: typing.Union[discord.User, discord.TextChannel, discord.Thread]):
        """
        exclude user or channel from gaining XP

        :param ctx: discord context
        :param userorchannel: user or channel to disallow gaining XP.
        """
        async with database.db.execute("SELECT 1 FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                              (ctx.guild.id, ctx.author.id)) as cur:
            if await cur.fetchone() is not None:
                exists = True
                await database.db.execute("DELETE FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                 (ctx.guild.id, ctx.author.id))
            else:
                exists = False
                await database.db.execute("INSERT INTO guild_xp_exclusions(guild, userorchannel, mod_set) VALUES (?,?,true)",
                                 (ctx.guild.id, ctx.author.id))
            await database.db.commit()
        await ctx.reply(f"✔️ {'Unexcluded' if exists else 'Excluded'} {userorchannel.mention} from XP.")

    @commands.command()
    async def togglemyxp(self, ctx: commands.Context):
        """
        enable or disable yourself from getting XP.
        """
        async with database.db.execute("SELECT mod_set FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                              (ctx.guild.id, ctx.author.id)) as cur:
            res = await cur.fetchone()
            # user is not excluded from guild
            if res is None:
                result = "Disabled"
                await database.db.execute(
                    "INSERT INTO guild_xp_exclusions(guild, userorchannel, mod_set) VALUES (?,?,false)",
                    (ctx.guild.id, ctx.author.id))
                await database.db.commit()
            # user is excluded but not by a mod
            elif not res[0]:
                result = "Enabled"
                await database.db.execute("DELETE FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                 (ctx.guild.id, ctx.author.id))
                await database.db.commit()
            # user is excluded by a mod, dont let them reenable xp on their own
            else:
                result = "Blocked"
        if result == "Blocked":
            await ctx.reply(f"❌ Your XP has been disabled by a moderator. Contact a moderator to get your XP "
                            f"re-enabled.\nIf you are a moderator, use `m.excludefromxp`.")
        else:
            # enabled or disabled
            await ctx.reply(f"✔️ {result} your XP.")

    # TODO: rank command
    # TODO: leaderboard command
    # TODO: serverwide disable or enable
    # TODO: serverwide reset
    # TODO: user reset?
    # TODO: xp info command


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
