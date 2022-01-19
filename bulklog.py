import asyncio
import datetime
import io
import re
import typing

import aiosqlite
import nextcord as discord
from nextcord.ext import commands

import embedutils


class BulkLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def logdict(self, fields: dict, guildid: int, embed: typing.Optional[discord.Embed] = None,
                      color: discord.Colour = discord.Color.blurple()):
        # most actions will work fine with the simple dict format but some might want to modify
        # the embed, easiest way is to allow them to pass their own embed
        if embed is None:
            embed = discord.Embed(title="Server Log", color=color,
                                  timestamp=datetime.datetime.now(tz=datetime.timezone.utc))
        files = []
        for k, v in fields.items():
            v = str(v)
            if len(v) < 6000:
                embedutils.add_long_field(embed, k, v)
            else:
                pattern = re.compile(r'[\W_]+')
                fname = pattern.sub('', k) + ".txt"
                files.append(discord.File(io.BytesIO(v.encode("utf8")), fname))
                embed.add_field(name=k, value=f"see attached file `{fname}`")
        await self.log(embed, guildid, files)

    async def log(self, embed: discord.Embed, guildid: int, files: typing.Optional[typing.List[discord.File]] = None):
        """
        log generated embed to server bulk log channel
        :param guildid: ID of guild
        :param embed: embed object, passed through embedutils.split_embed() to .send()
        :param files: list of files, passed straight to .send()
        """
        async with aiosqlite.connect("database.sqlite") as db:
            async with db.execute("SELECT bulk_log_channel FROM server_config WHERE guild=?", (guildid,)) as cur:
                modlogchannel = await cur.fetchone()
            if modlogchannel is None or modlogchannel[0] is None:
                return
            modlogchannel = modlogchannel[0]
            channel = await self.bot.fetch_channel(modlogchannel)
            await channel.send(embeds=embedutils.split_embed(embed), files=files,
                               )

    @commands.Cog.listener()
    async def on_message_delete(self, msg: discord.Message):
        await self.logdict({
            "Action": "Message Delete",
            "Channel": f"{msg.channel.mention} (#{msg.channel})",
            "Author": f"{msg.author.mention} (@{msg.author})",
            "Content": msg.system_content,
            "Links": "\n".join([att.url for att in msg.attachments] + [emb.url for emb in msg.embeds
                                                                       if emb.url != discord.Embed.Empty])
                     or "No Embeds or Attachments",
            "Timestamp": f"<t:{int(msg.created_at.timestamp())}:F>",
            "Message ID": str(msg.id)
        }, msg.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, msgs: typing.List[discord.Message]):
        await self.logdict({
            "Action": "Bulk Message Delete",
            "Channel": f"{msgs[0].channel.mention} (#{msgs[0].channel})",
            "Number of Messages Deleted": str(len(msgs))
        }, msgs[0].guild.id, color=discord.Colour.red())
        await asyncio.wait([self.on_message_delete(msg) for msg in msgs])

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        await self.logdict({
            "Action": "Message Edit",
            "Channel": f"{after.channel.mention} (#{after.channel})",
            "Author": f"{after.author.mention} (@{after.author})",
            "Content Before": before.system_content,
            "Content After": after.system_content,
            "Message ID": str(after.id),
            "Message Jump URL": after.jump_url
        }, after.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: typing.Union[discord.Member, discord.User]):
        await self.logdict({
            "Action": "Reaction Remove",
            "Channel": f"{reaction.message.channel.mention} (#{reaction.message.channel})",
            "Author": f"{reaction.message.author.mention} (@{reaction.message.author})",
            "Reaction author": f"{user.mention} (@{user})",
            "Reaction Removed": str(reaction.emoji),
            "Message ID": str(reaction.message.id),
            "Message Jump URL": reaction.message.jump_url
        }, reaction.message.guild.id, color=discord.Colour.orange())

    @commands.Cog.listener()
    async def on_reaction_clear(self, msg: discord.Message, reactions: typing.List[discord.Reaction]):
        await self.logdict({
            "Action": "Reaction Clear",
            "Channel": f"{msg.channel.mention} (#{msg.channel})",
            "Author": f"{msg.author.mention} (@{msg.author})",
            "Reactions Cleared": " ".join([f"{reaction.emoji}x{reaction.count}" for reaction in reactions]),
            "Message ID": str(msg.id),
            "Message Jump URL": msg.jump_url
        }, msg.guild.id, color=discord.Colour.orange())

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self.logdict({
            "Action": "Channel Create",
            "Channel": f"{channel.mention} (#{channel})",
            "Category": channel.category.name if channel.category else "No Category",
            "Channel ID": str(channel.id)
        }, channel.guild.id, color=discord.Colour.green())

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self.logdict({
            "Action": "Channel Delete",
            "Channel": f"{channel.mention} (#{channel})",
            "Category": channel.category.name if channel.category else "No Category",
            "Channel ID": str(channel.id)
        }, channel.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel, ):
        await self.logdict({
            "Action": "Channel Update",
            "Before": f"{before.mention} (#{before}) "
                      f"in category {before.category.name if before.category else 'No Category'}",
            "After": f"{after.mention} (#{after}) "
                     f"in category {after.category.name if after.category else 'No Category'}",
            "Channel ID": str(after.id)
        }, after.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel: typing.Union[discord.TextChannel, discord.Thread],
                                           last_pin: typing.Optional[datetime.datetime]):
        pins = await channel.pins()
        await self.logdict({
            "Action": "Channel Pins Update",
            "Channel": f"{channel.mention} (#{channel})",
            "Category": channel.category.name if channel.category else "No Category",
            "Channel ID": str(channel.id),
            "# of Pins": len(pins),
            "Pinned messages": ", ".join([str(pin.id) for pin in pins]) or "No pins",
            "Time of last pin": f"<t:{int(last_pin.timestamp())}:F>" if last_pin else "unknown"
        }, channel.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        await self.logdict({
            "Action": "Thread Delete",
            "Owner": f"{thread.owner.mention} (@{thread.owner})",
            "Thread": f"{thread.mention} (#{thread})",
            "Parent Channel": f"{thread.parent.mention} (#{thread.parent})",
            "Thread ID": str(thread.id)
        }, thread.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        await self.logdict({
            "Action": "Thread Create",
            "Owner": f"{thread.owner.mention} (@{thread.owner})",
            "Thread": f"{thread.mention} (#{thread})",
            "Parent Channel": f"{thread.parent.mention} (#{thread.parent})",
            "Thread ID": str(thread.id)
        }, thread.guild.id, color=discord.Colour.green())

    @commands.Cog.listener()
    async def on_thread_member_join(self, member: discord.ThreadMember):
        truemember = member.thread.guild.get_member(member.id)
        await self.logdict({
            "Action": "Thread Join",
            "User": f"{truemember.mention} (@{truemember})",
            "Thread": f"{member.thread.mention} (#{member.thread})",
            "Parent Channel": f"{member.thread.parent.mention} (#{member.thread.parent})",
            "Thread ID": str(member.thread.id)
        }, member.thread.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_thread_member_remove(self, member: discord.ThreadMember):
        truemember = member.thread.guild.get_member(member.id)
        await self.logdict({
            "Action": "Thread Leave",
            "User": f"{truemember.mention} (@{truemember})",
            "Thread": f"{member.thread.mention} (#{member.thread})",
            "Parent Channel": f"{member.thread.parent.mention} (#{member.thread.parent})",
            "Thread ID": str(member.thread.id)
        }, member.thread.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        await self.logdict({
            "Action": "Thread Update",
            "Owner": f"{after.owner.mention} (@{after.owner})",
            "Thread": f"{after.mention} (#{before} -> #{after})",
            "Parent Channel": f"{after.parent.mention} (#{after.parent})",
            "Thread ID": str(after.id)
        }, after.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        await self.logdict({
            "Action": "Integration Update",
        }, guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.TextChannel):
        await self.logdict({
            "Action": "Webhooks Update",
            "Channel": f"{channel.mention} (#{channel})",
            "Webhooks": "\n".join([f"{webhook.name} ({webhook.id}" for webhook in await channel.webhooks()])
        }, channel.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.logdict({
            "Action": "Member Join",
            "User": f"{member.mention} (@{member})",
            "User ID": str(member.id)
        }, member.guild.id, color=discord.Colour.green())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.logdict({
            "Action": "Member Left",
            "User": f"{member.mention} (@{member})",
            "Nickname": member.nick or "No Nickname",
            "Roles": ", ".join([role.mention for role in member.roles]) or "None",
            "User ID": str(member.id)
        }, member.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        await self.logdict({
            "Action": "Member Update",
            "User": f"{after.mention} (@{after})",
            "Nickname Before": before.nick or "No Nickname",
            "Roles Before": ", ".join([role.mention for role in before.roles]) or "None",
            "Nickname After": after.nick or "No Nickname",
            "Roles After": ", ".join([role.mention for role in after.roles]) or "None",
            "User ID": str(after.id)
        }, after.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        await self.logdict({
            "Action": "Guild Update",
            "Guild ID": str(after.id)
        }, after.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self.logdict({
            "Action": "Role Create",
            "Role": f"{role.mention} ({role.name})",
            "Role ID": str(role.id)
        }, role.guild.id, color=discord.Colour.green())

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.logdict({
            "Action": "Role Delete",
            "Role": f"{role.mention} ({role.name})",
            "Role ID": str(role.id)
        }, role.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        await self.logdict({
            "Action": "Role Update",
            "Role": f"{after.mention} ({before.name} -> {after.name})",
            "Role ID": str(after.id)
        }, after.guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: typing.Sequence[discord.Emoji],
                                     after: typing.Sequence[discord.Emoji]):
        deleted = list(set(before) - set(after))
        added = list(set(after) - set(before))
        await self.logdict({
            "Action": "Emoji Update",
            "Emojis Removed": " ".join([str(e) for e in deleted]) or "None",
            "Emojis Added": " ".join([str(e) for e in added]) or "None",
        }, guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before: typing.Sequence[discord.GuildSticker],
                                       after: typing.Sequence[discord.GuildSticker]):
        deleted = list(set(before) - set(after))
        added = list(set(after) - set(before))
        await self.logdict({
            "Action": "Sticker Update",
            "Stickers Removed": ", ".join([f"`{e}`" for e in deleted]) or "None",
            "Stickers Added": ", ".join([f"`{e}`" for e in added]) or "None",
        }, guild.id, color=discord.Colour.yellow())

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, member: discord.User):
        await self.logdict({
            "Action": "User Unban",
            "User": f"{member.mention} (@{member})",
            "User ID": str(member.id)
        }, guild.id, color=discord.Colour.green())

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        await self.logdict({
            "Action": "Invite Delete",
            "Invite": str(invite),
            "Invite ID": str(invite.id)
        }, invite.guild.id, color=discord.Colour.red())

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        await self.logdict({
            "Action": "Invite Create",
            "Invite": str(invite),
            "Invite ID": str(invite.id)
        }, invite.guild.id, color=discord.Colour.green())

    # @commands.Cog.listener()
    # async def on_user_update(self, before: discord.User, after: discord.User):
    #     await self.logdict({
    #         "Action": "User Update",
    #         "User": f"{after.mention} (@{before} -> @{after})",
    #         "User ID": str(after.id)
    #     }, NONE, color=discord.Colour.yellow())

    '''
    Steps to convert:
    @bot.command() -> @commands.command()
    @bot.listen() -> @commands.Cog.listener()
    function(ctx): -> function(self, ctx)
    bot -> self.bot
    '''
