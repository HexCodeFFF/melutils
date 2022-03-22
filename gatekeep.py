import asyncio

import nextcord
import nextcord as discord
from nextcord.ext import commands

import database
import modlog
from moderation import update_server_config, mod_only


class GateKeep(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot

    @commands.Cog.listener()
    async def on_member_leave(self, member: discord.Member):
        async with database.db.execute("SELECT thread FROM members_to_verify WHERE guild=? AND member=?",
                                       (member.guild.id, member.id)) as cur:
            res = await cur.fetchone()
            if res and res[0]:
                th = member.guild.get_thread(res[0])
                await th.remove_user(member)
                await th.edit(archived=True, locked=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with database.db.execute(
                "SELECT verification_channel,mod_role,verified_role,verification_text FROM server_config WHERE guild=?",
                (member.guild.id,)) as cur:
            res = await cur.fetchone()
        if res and res[0]:
            if "PRIVATE_THREADS" in member.guild.features:
                # create thread
                thread = await member.guild.get_channel(res[0]) \
                    .create_thread(name=f"Verification for {member}", reason=f"Automatic verification for {member}")
            else:
                thread = await member.guild.get_channel(res[0]) \
                    .create_thread(name=f"Verification for {member}", reason=f"Automatic verification for {member}",
                                   type=discord.ChannelType.public_thread)

                # delete the thread announcement message cause hehehahgrrrrr
                async def delthread():
                    async for msg in member.guild.get_channel(res[0]).history():
                        if msg.flags.has_thread and msg.thread == thread:
                            await msg.delete()
                            break

                asyncio.create_task(delthread())
                # add to db
            await database.db.execute("INSERT INTO members_to_verify (guild, member, thread) VALUES (?,?,?)",
                                      (member.guild.id, member.id, thread.id))
            await database.db.commit()
            # add mods and user to thread
            if res[1]:
                modping = member.guild.get_role(res[1]).mention
            else:
                modping = member.guild.owner.mention
            await thread.send(f"{modping} {member.mention}\n{res[3]}",
                              allowed_mentions=nextcord.AllowedMentions.all())

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def verificationchannel(self, ctx, *, channel: discord.TextChannel = None):
        """
        Sets the server verification channel.
        All new members will get a thread on this channel which a moderator must approve.

        :param ctx: discord context
        :param channel: - The verification channel, leave blank to remove verificatio from this server
        """
        if channel is None:
            await update_server_config(ctx.guild.id, "verification_channel", None)
            await ctx.reply("✔️ Removed server verification channel.")
        else:
            await update_server_config(ctx.guild.id, "verification_channel", channel.id)
            await ctx.reply(f"✔️ Set server verification channel to **{channel.mention}**")

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def initverification(self, ctx: commands.Context):
        """
        Set up the verification role and channel if it doesn't exist.
        """

        def remove_perms(p: discord.Permissions):
            p.update(view_channel=False)
            return p

        msg = await ctx.send("⚙️ Setting up verification role, this will take a minute...")
        async with ctx.typing():

            # get or create role
            async with database.db.execute(
                    "SELECT verified_role,verification_channel,mod_role from server_config WHERE guild=?",
                    (ctx.guild.id,)) as cur:
                res = await cur.fetchone()
            # action only needs to be taken if role does not exist
            if not (res and res[0] and (verified_role := ctx.guild.get_role(res[0]))):
                verified_role = await ctx.guild.create_role(name="[MelUtils] Verified",
                                                            permissions=discord.Permissions(view_channel=True))
                await database.db.execute("UPDATE server_config SET verified_role=? WHERE guild=?",
                                          (verified_role.id, ctx.guild.id))
            if res and res[2]:
                mod_role = ctx.guild.get_role(res[2])
            else:
                mod_role = None
            ovrs = {
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                                    send_messages_in_threads=True),
                verified_role: discord.PermissionOverwrite(view_channel=False)
            }
            if mod_role:
                ovrs[mod_role] = discord.PermissionOverwrite(view_channel=True)
            if not (res and res[1] and (verify_channel := ctx.guild.get_channel(res[1]))):
                verify_channel = await ctx.guild.create_text_channel("melutils-verification", overwrites=ovrs)
                await database.db.execute("UPDATE server_config SET verification_channel=? WHERE guild=?",
                                          (verify_channel.id, ctx.guild.id))
            else:  # channel exists
                # update its overwrites properly
                verify_channel.overwrites.update(ovrs)
                await verify_channel.edit(overwrites=verify_channel.overwrites)

            await database.db.commit()

            # give verified role to all members
            v_actions = [m.add_roles(verified_role) for m in ctx.guild.members if verified_role not in m.roles]
            await asyncio.gather(*v_actions, return_exceptions=True)

            # remove view perms from all roles
            role_actions = [r.edit(permissions=remove_perms(r.permissions)) for r in ctx.guild.roles if
                            r.permissions.view_channel and r != verified_role]
            ch_actions = []
            for ch in ctx.guild.channels:
                if ch == verify_channel:
                    continue
                # if the channel has view channel explicitly allowed for @everyone, uhhh undo that!
                def_ovr = ch.overwrites_for(ctx.guild.default_role)
                if def_ovr.view_channel:
                    prms = ch.overwrites[ctx.guild.default_role]
                    prms.update(view_channel=None, read_messages=None)
                    ovrs = ch.overwrites
                    ovrs.update({ctx.guild.default_role: prms})
                    ch_actions.append(ch.edit(overwrites=ovrs))

            await asyncio.gather(*role_actions, *ch_actions, return_exceptions=True)
            await msg.delete()
            await modlog.modlog(f"{ctx.author.mention} (@{ctx.author}) initialized verification. New members will now "
                                f"need to be verified.", ctx.guild.id,
                                ctx.author.id)
        await ctx.reply(f"✔️ Done!\nSee {verified_role.mention} and {verify_channel.mention}.")

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    async def verificationtext(self, ctx, *, text: str = None):
        """
        Sets the server verification text
        New members will be sent this text in their verification thread

        :param ctx: discord context
        :param text: - The verification text
        """
        if text is None:
            await update_server_config(ctx.guild.id, "verification_text", "Please wait for a moderator to verify you.")
            await ctx.reply("✔️ Set server verification text to default.")
        else:
            await update_server_config(ctx.guild.id, "verification_text", text)
            await ctx.reply(f"✔️ Set server verification text to `{text}`")

    @commands.command()
    @mod_only()
    async def verify(self, ctx: commands.Context):
        """
        verifies a member of a given thread
        """
        async with database.db.execute(
                "SELECT member FROM members_to_verify WHERE guild=? AND thread=?",
                (ctx.guild.id, ctx.channel.id)) as cur:
            res = await cur.fetchone()
        # if we can find the relevant member for the channel
        if res and res[0]:
            member = ctx.guild.get_member(res[0])
            async with database.db.execute("SELECT verified_role FROM server_config WHERE guild=?",
                                           (ctx.guild.id,)) as cur:
                res2 = await cur.fetchone()
            # if we can get the guild's verifed role, add it and
            if res2 and res2[0]:
                role = ctx.guild.get_role(res2[0])
                await ctx.send(f"{member.mention} has been verified.")
                await member.add_roles(role)
                # lock thread, hide from user cause lol?
                await ctx.channel.remove_user(member)
                await ctx.channel.edit(archived=True, locked=True)
                await modlog.modlog(f"{ctx.author.mention} (@{ctx.author}) verified {member.mention} (@{member})",
                                    ctx.guild.id, member.id, ctx.author.id)
            else:
                await ctx.reply("❌ Server has no verified role. Run `m.initverification` to create one.")
        else:
            await ctx.reply(f"❌ Unable to verify. Are you sending this inside the member's verification thread?")


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx, ...): -> function(self, ctx, ...)
bot -> self.bot
'''
