import typing

import aiosqlite
import emojis
import nextcord as discord
from nextcord.ext import commands
from nextcord.http import Route

import moderation
import database


class UnicodeEmojiNotFound(commands.BadArgument):
    def __init__(self, argument):
        self.argument = argument
        super().__init__(f'Unicode emoji "{argument}" not found.')


class UnicodeEmojiConverter(commands.Converter):
    async def convert(self, ctx, argument) -> str:
        emoji = emojis.db.get_emoji_by_code(argument)
        if not emoji:
            raise UnicodeEmojiNotFound(argument)
        # `emoji` is a named tuple.
        # see: https://github.com/alexandrevicenzi/emojis/blob/master/emojis/db/db.py#L8
        # we already confirmed it's a valid emoji, so lets return the codepoint back
        return emoji.emoji


def booster_only():
    async def extended_check(ctx: commands.Context):
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        if ctx.author.premium_since is not None:
            return True
        raise commands.CheckFailure("You need to be a server booster to run this command.")

    return commands.check(extended_check)


class NitroRolesCog(commands.Cog, name="Booster Roles"):
    def __init__(self, bot):
        self.bot: commands.Bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # they lost booster role, removed boost.
        if after.guild.premium_subscriber_role in before.roles and \
                after.guild.premium_subscriber_role not in after.roles:
            self.bot.dispatch("on_booster_remove", after)
        # they gained booster role, added boost
        if after.guild.premium_subscriber_role in after.roles and \
                after.guild.premium_subscriber_role not in before.roles:
            self.bot.dispatch("on_booster_add", after)

    @commands.Cog.listener()
    async def on_booster_remove(self, member: discord.Member):
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (member.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (member.guild.id, member.id))
            role = await cur.fetchone()
            if role is not None:
                role = member.guild.get_role(role[2])
                if role is not None:
                    await member.remove_roles(role)
                    await member.send(f"It seems you've stopped boosting **{member.guild.name}**! Your booster role"
                                      f" ({role.mention}) has been removed. You can get it back by re-boosting the "
                                      f"server.")

    @commands.Cog.listener()
    async def on_booster_add(self, member: discord.Member):
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (member.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (member.guild.id, member.id))
            role = await cur.fetchone()
            if role is not None:
                role = member.guild.get_role(role[2])
                if role is not None:
                    await member.add_roles(role)
                    await member.send(f"Thank you for boosting **{member.guild.name}**! It seems you already have "
                                      f"a booster role, so I have given it to you. You can modify this role with "
                                      f"the commands `m.boosterrole`, `m.boosterrolecolor`, "
                                      f"and `m.boosterroleicon`.")
                    return
            await member.send(f"Thank you for boosting **{member.guild.name}**! One of the perks of boosting this "
                              f"server is your very own custom booster role! You can modify this role with "
                              f"the commands `m.boosterrole`, `m.boosterrolecolor`, "
                              f"and `m.boosterroleicon`.")

    @booster_only()
    @commands.command()
    async def boosterrole(self, ctx: commands.Context, *, name: str = None):
        """
        create or change the name of your booster role
        :param ctx: discord context
        :param name: the name of your booster role, leave blank to remove.
        """
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (ctx.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (ctx.guild.id, ctx.author.id))
            role = await cur.fetchone()
            if role is not None:
                role = ctx.guild.get_role(role[2])
                if role is not None:
                    if name:
                        await role.edit(name=name)
                        await ctx.reply(f"✔️ Updated your booster role name: {role.mention}",
                                        )
                    else:
                        await role.delete()
                        await database.db.execute("DELETE FROM booster_roles WHERE guild=? AND user=?",
                                         (ctx.guild.id, ctx.author.id))
                        await database.db.commit()
                        await ctx.reply("✔️ Deleted your booster role")
                    return
                if name is None:
                    await ctx.reply("❓ Specify a name for your role")
                    return
            role = await ctx.guild.create_role(name=name, hoist=True)
            cur: aiosqlite.Cursor = await database.db.execute(
                "SELECT booster_role_hoist FROM main.server_config WHERE guild=?",
                (ctx.guild.id,))
            booster_role_hoist = await cur.fetchone()
            if booster_role_hoist is not None and booster_role_hoist[0] is not None:
                booster_role_hoist = ctx.guild.get_role(booster_role_hoist[0])
                if booster_role_hoist is not None:
                    await ctx.guild.edit_role_positions({role: booster_role_hoist.position - 1})
            await ctx.author.add_roles(role)
            await database.db.execute(
                "REPLACE INTO booster_roles (guild, user, role) VALUES (?, ?, ?)",
                (ctx.guild.id, ctx.author.id, role.id))
            await database.db.commit()
            await ctx.reply(f"✔️ Created your booster role: {role.mention}")
        else:
            await ctx.reply("❌ Booster roles are not enabled on this server.")

    @booster_only()
    @commands.command()
    async def boosterrolecolor(self, ctx: commands.Context, *, color: discord.Color = None):
        """
        change the color of your booster role
        :param ctx: discord context
        :param color: hex or RGB color
        """
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (ctx.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (ctx.guild.id, ctx.author.id))
            role = await cur.fetchone()
            if role is not None:
                role = ctx.guild.get_role(role[2])
                if role is not None:
                    if color:
                        await role.edit(color=color)
                        await ctx.reply(f"✔️ Updated your booster role color: {role.mention}",
                                        )
                    else:
                        await role.edit(color=discord.Color.default())
                        await ctx.reply(f"✔️ Deleted your booster role color: {role.mention}",
                                        )
                    return
            await ctx.reply("❌ You do not have a booster role. Create one with `m.boosterrole`")
        else:
            await ctx.reply("❌ Booster roles are not enabled on this server.")

    # @boosterrolecolor.error
    # async def boosterrolecolorerror(self, ctx: commands.Context, error: Exception):
    #     if isinstance(error, commands.MissingRequiredArgument) and \
    #             ctx.current_parameter == self.boosterrolecolor.params['color']:
    #         return logger.debug("some handled behavior")
    #     else:
    #         return await errhandler.on_command_error(ctx, error, True)

    def edit_role_icon(self, role: discord.Role, icon: typing.Union[bytes, str, None], *,
                       reason: typing.Optional[str] = None):
        payload = {
            'name': role.name,
            'permissions': role.permissions.value,
            'color': role.color.value,
            'hoist': role.hoist,
            'mentionable': role.mentionable,
            'unicode_emoji': None,
            'icon': None
        }
        if isinstance(icon, str):
            payload['unicode_emoji'] = icon
        elif isinstance(icon, bytes):
            payload['icon'] = discord.utils._bytes_to_base64_data(icon)
        r = Route('PATCH', '/guilds/{guild_id}/roles/{role_id}', guild_id=role.guild.id, role_id=role.id)
        return self.bot.http.request(r, json=payload, reason=reason)

    @booster_only()
    @commands.command()
    async def boosterroleicon(self, ctx: commands.Context, *,
                              icon: typing.Union[UnicodeEmojiConverter, discord.Emoji] = None):
        """
        change the icon of your booster role

        :param ctx: discord context
        :param icon: a unicode or discord emoji. leave blank to set icon to attachment or delete icon if no attachments
        """
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (ctx.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (ctx.guild.id, ctx.author.id))
            role = await cur.fetchone()
            if role is not None:
                role = ctx.guild.get_role(role[2])
                if role is not None:
                    if icon:
                        if isinstance(icon, discord.Emoji):
                            icon = await icon.read()
                        await self.edit_role_icon(role, icon)
                        await ctx.reply(f"✔️ Updated your booster role icon: {role.mention}",
                                        )
                    else:
                        if ctx.message.attachments:
                            await self.edit_role_icon(role, await ctx.message.attachments[0].read())
                            await ctx.reply(f"✔️ Updated your booster role icon: {role.mention}",
                                            )
                        else:
                            await self.edit_role_icon(role, None)
                            await ctx.reply(f"✔️ Deleted your booster role icon: {role.mention}",
                                            )
                    return
            await ctx.reply("❌ You do not have a booster role. Create one with `m.boosterrole`")
        else:
            await ctx.reply("❌ Booster roles are not enabled on this server.")

    @moderation.mod_only()
    @commands.command()
    async def boosterroles(self, ctx: commands.Context, enabled: bool):
        """
        moderation command to enable or disable custom roles for boosters
        :param ctx: discord context
        :param enabled: to enable or disable the roles
        """
        await moderation.update_server_config(ctx.guild.id, "booster_roles", enabled)
        await ctx.reply(f"✔️ {'Enabled' if enabled else 'Disabled'} booster roles.")

    @moderation.mod_only()
    @commands.command()
    async def boosterroleshoist(self, ctx: commands.Context, hoist: discord.Role = None):
        """
        moderation command to set a role for booster roles to be created underneath
        :param ctx: discord context
        :param hoist: the role that all new booster roles will be moved under. leave blank to disable.
        """
        if hoist:
            await moderation.update_server_config(ctx.guild.id, "booster_role_hoist", hoist.id)
            await ctx.reply(f"✔️ Set booster role hoist to {hoist.mention}.",
                            )
        else:
            await moderation.update_server_config(ctx.guild.id, "booster_role_hoist", None)
            await ctx.reply(f"✔️ Disabled booster role hoist.",
                            )

    @moderation.mod_only()
    @commands.command()
    async def setboosterrole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        """
        moderation command to designate a specific role as a booster role.
        :param ctx: discord context
        :param member: the member to assign the role to
        :param role: the role to set as the booster role
        """
        cur: aiosqlite.Cursor = await database.db.execute("SELECT booster_roles FROM main.server_config WHERE guild=?",
                                                 (ctx.guild.id,))
        booster_roles = await cur.fetchone()
        if booster_roles:
            cur: aiosqlite.Cursor = await database.db.execute("SELECT * FROM booster_roles WHERE guild=? AND user=?",
                                                     (ctx.guild.id, member.id))
            oldrole = await cur.fetchone()
            if oldrole is not None:
                oldrole = ctx.guild.get_role(oldrole[2])
                if oldrole is not None:
                    await member.remove_roles(oldrole)
            await member.add_roles(role)
            await database.db.execute("REPLACE INTO booster_roles (guild, user, role) VALUES (?,?,?)",
                             (ctx.guild.id, member.id, role.id))
            await database.db.commit()
            await ctx.reply(f"✔️ Set {member.mention}'s booster role to {role.mention}.",
                            )
        else:
            await ctx.reply("❌ Booster roles are not enabled for this server.")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''
