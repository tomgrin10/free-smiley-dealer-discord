import asyncio
import copy
import json
import logging
import random
from typing import *

import discord
from discord.ext import commands

import extensions
from .converters import SettingsDefaultConverter, SettingsChannelConverter
from database import Database, is_enabled, author_not_muted

# Constants
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}


def iterate_emojis_in_string(string: str) -> Iterator[str]:
    """
    List all emojis in a string.
    """
    for char in string:
        if char in DISCORD_EMOJI_TO_CODE:
            yield char


async def settings_ask_channel_or_server(ctx: commands.Context, msg_content: str) -> Union[Type[discord.Guild], Type[discord.TextChannel]]:
    emojis_dict = {discord.Guild: "🇸", discord.TextChannel: "🇨"}

    msg_content = msg_content.replace("channel", f"{emojis_dict[discord.TextChannel]}hannel").replace("server", f"{emojis_dict[discord.Guild]}erver")
    emojis = sorted(emojis_dict.values(), key=lambda e: msg_content.find(e))

    question_msg: discord.Message = await ctx.send(msg_content)
    try:
        answer_emoji = str(await ctx.bot.ask_question(question_msg, ctx.author, emojis=emojis, timeout=20))
    except asyncio.TimeoutError:
        raise commands.BadArgument("Operation cancelled.")
    finally:
        await question_msg.delete()

    question_result = {v: k for k, v in emojis_dict.items()}[answer_emoji]
    return None if question_result == discord.Guild else ctx.channel


def to_emoji_name(arg: str) -> str:
    if arg in DISCORD_EMOJI_TO_CODE:
        return DISCORD_EMOJI_TO_CODE[arg].replace(':', '')

    raise commands.BadArgument("Not an emoji.")


def get_cooldown(message: discord.Message) -> commands.Cooldown:
    global cog

    rate, per = cog.db.Setting("cooldown", message.guild.id, message.channel.id).read()
    return commands.Cooldown(rate, per, commands.BucketType.channel)


def check_if_bot_admin(ctx: commands.Context):
    return ctx.author.id in ctx.bot.config["admin_users_id"]


class FreeSmileyDealerCog:
    def __init__(self, bot: 'extensions.BasicBot', db: Optional[Database] = None):
        global cog
        cog = self
        self.bot = bot

        self.db = db or Database()
        self.smiley_emojis_dict = dict()

        self.bot.remove_command("help")

    def setup_smiley_emojis_dict(self):
        """
        Set up dictionary of smiley emojis.
        """
        emoji_guilds = (self.bot.get_guild(int(id)) for id in self.db.config["emoji_guilds_id"])
        all_smiley_emojis = sum((guild.emojis for guild in emoji_guilds), tuple())

        for emoji_names in self.db.static_data["smileys"]:
            smiley_name = emoji_names[0]
            current_smiley_emojis = (e for e in all_smiley_emojis if e.name.startswith(smiley_name))
            self.smiley_emojis_dict[smiley_name] = sorted(current_smiley_emojis, key=lambda e: e.name.split('_')[-1])

    async def on_ready(self):
        self.setup_smiley_emojis_dict()

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        def format(msg) -> str:
            """Command error format for user."""
            return f":x: **{msg}**"

        # Missing permissions to run command
        if isinstance(error, commands.MissingPermissions):
            perm = error.missing_perms[0].replace('_', ' ').replace('guild', 'server').title()
            await ctx.send(format(f"This command requires you to have `{perm}` permission to use it."))

        # User gave bad arguments
        elif isinstance(error, commands.BadArgument):
            await ctx.send(format(error))

        elif isinstance(error, commands.BadUnionArgument):
            await ctx.send(format(error.errors[1]))

        # Ignore error
        elif isinstance(error, commands.CheckFailure):
            return

        # Error while executing a command
        if isinstance(error, commands.CommandInvokeError) or __debug__:
            logging.exception(error)
            try:
                await ctx.send(format("An error has occurred."))
            except discord.Forbidden:
                pass

    def get_smiley_name(self, emoji_name: str) -> Optional[str]:
        # Iterate emojis in data
        for emoji_names in self.db.static_data["smileys"]:
            if emoji_name in emoji_names:
                return emoji_names[0]

    def get_smiley_reaction_emoji(self, emoji_name: str) -> Optional[discord.Emoji]:
        # Get smiley name from emoji name
        smiley_name = self.get_smiley_name(emoji_name)
        if not smiley_name or smiley_name not in self.smiley_emojis_dict:
            return

        emojis = self.smiley_emojis_dict[smiley_name]
        if not emojis:
            return

        return random.choice(emojis)

    async def on_message(self, message: discord.Message):
        # Check if not myself or user not a bot
        if message.author == self.bot.user or message.author.bot:
            return

        # Check if message executes command
        ctx: commands.Context = await self.bot.get_context(message)
        if not ctx.valid:
            # Get first emoji in message
            emoji = next(iterate_emojis_in_string(message.content), None)
            if emoji:
                # Invoke command to answer with appropriate smiley
                new_message = copy.copy(message)
                new_message.content = emoji
                new_ctx: commands.Context = await self.bot.get_context(new_message)
                command: commands.Command = self.bot.get_command("_on_message")
                new_ctx.command = command
                await self.bot.invoke(new_ctx)

    @extensions.command(name="_on_message", hidden=True)
    @commands.guild_only()
    @is_enabled()
    @author_not_muted()
    async def command__on_message(self, ctx: commands.Context, emoji: str):
        emoji_name = DISCORD_EMOJI_TO_CODE[emoji].replace(':', '')

        async def send_smiley_emoji():
            emoji = self.get_smiley_reaction_emoji(emoji_name)
            if emoji:
                await ctx.send(f"{ctx.author.mention} {random.choice(self.db.static_data['titles'])}")
                await ctx.send(str(emoji))

        async def react_with_smiley():
            emoji = self.get_smiley_reaction_emoji(emoji_name)
            if emoji:
                await ctx.message.add_reaction(emoji)

        # Regular mode
        if not self.db.Setting("lite_mode", ctx.guild.id, ctx.channel.id).read():
            await send_smiley_emoji()

        # Lite mode
        else:
            await react_with_smiley()

    @extensions.command(name="help", aliases=["h"])
    async def command_help(self, ctx: commands.Context, command: extensions.CommandConverter = None):
        def command_to_embed(command: extensions.Command, embed: discord.Embed = None, *, long: bool = False) -> discord.Embed:
            """Add a field for the command in an embed or create an embed for the command."""
            def command_full_name(c: extensions.Command) -> str:
                # Setup name
                name = f"{c.emoji or ':red_circle:'} {c.name}"

                if c.aliases:
                    name += f" | {sorted(c.aliases, key=len)[0]}"

                return name

            # Setup name
            name = command_full_name(command)
            # Setup opposite command
            if command.opposite:
                name += f" {command_full_name(ctx.bot.get_command(command.opposite))}"

            value = ""
            # Command brief description
            explanation = command.description if long and command.description else command.brief
            if explanation:
                value += f"{explanation}"
            command_call = f"{self.bot.config['prefix']}{sorted([command.name] + command.aliases, key=len)[0]}"
            # Command usage format
            if command.usage:
                value += f"\n**Format:** {command_call} {command.usage}"
            # Command examples
            if command.examples:
                if len(command.examples) == 1:
                    value += f"\n**Example:** {command_call} {command.help}"
                else:
                    value += f"\n**Examples:** {', '.join(f'{command_call} {example}' for example in command.examples)}"

            if embed:
                embed.add_field(name=name, value=value, inline=not (command.usage or command.help))
                return embed
            else:
                return discord.Embed(title=name, description=value)

        if command:
            embed = command_to_embed(command, long=True)
            embed.colour = 0xf3f702
            await ctx.send(embed=embed)
            return

        # Send message to channel
        heart_emoji = self.smiley_emojis_dict["heart"][0]
        help_message = (f":heart: -> {heart_emoji} If you use paid smileys (emojis) in your message, I will correct you.\n"
                        "Type `:joy:` to try it out!\n")
        if ctx.guild:
            help_message += ":scroll: For more commands look at your private messages."
        await ctx.send(help_message)

        def create_commands_embed(*, command_names: Sequence, **kwargs) -> discord.Embed:
            """Create an embed with given commands."""
            embed = discord.Embed(**kwargs)
            for command_name in command_names:
                command_to_embed(ctx.bot.get_command(command_name), embed)

            return embed

        # Commands embed
        await ctx.author.send(embed=create_commands_embed(
            title=":information_source: Commands",
            colour=0xf3f702,
            command_names=("invite", "server", "donate")))

        # Settings embed
        await ctx.author.send(embed=create_commands_embed(
            title=":gear: Settings",
            description="** You can add `s|server` `c|channel` `#some_channel` to the end of the command to specify where to change setting.\n"
                        "Example: s!lite on channel",
            colour=0x7bb3b5,
            command_names=("litemode", "blacklist", "mute")))

        await ctx.author.send(":+1: **Upvote me!** <https://discordbots.org/bot/475418097990500362/vote>\n"
                              f"**Join my server!** {self.bot.config['support_guild_url']}\n"
                              f"**Donate to keep the bot alive!** {self.bot.config['donate_url']}")

    @extensions.command(name="litemode", aliases=["lite"], category="settings",
                        brief="Litemode is a less spammy way to correct people.\nInstead of sending an image I will react with the smiley.",
                        usage="[on/off|*default*] [**]")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_litemode(self, ctx: commands.Context,
                               mode: Union[SettingsDefaultConverter, bool], target_channel: SettingsChannelConverter = "ask"):
        def on_off(b: bool):
            return "on" if b else "off"

        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you want to turn lite mode {on_off(mode)} for the channel or the server default?")

        # Update database
        self.db.Setting("lite_mode", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None)\
            .change(mode)

        # Send confirmation
        target_str = 'server default' if not target_channel else target_channel.mention
        await ctx.send(f":white_check_mark: {target_str.capitalize()} lite mode " +
                       (f"turned `{on_off(mode)}`." if mode is not None else f"returned to " +
                        (f"server default `{on_off(self.db.Setting('lite_mode', ctx.guild.id).read())}`." if target_channel else
                         f"global default `{on_off(self.db.get_global_default_setting('lite_mode'))}`.")))

    @extensions.command(name="blacklist", aliases=["bl"], category="settings", opposite="whitelist",
                        brief="Blacklist a channel from the bot.",
                        usage="[*optional*: channel]",
                        emoji=":mute:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_blacklist(self, ctx: commands.Context, target_channel: discord.TextChannel = None):
        if target_channel is None:
            target_channel = ctx.channel

        # Update database
        self.db.Setting("enabled", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None)\
            .change(False)

        target_str = target_channel.mention
        await ctx.send(f":mute: {target_str.capitalize()} has been blacklisted.")

    @extensions.command(name="whitelist", aliases=["wl", "unblacklist"], category="settings",
                        brief="Un-blacklist a channel from the bot.",
                        usage="[*optional*: channel]",
                        emoji=":speaker:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_whitelist(self, ctx: commands.Context, target_channel: discord.TextChannel = None):
        if target_channel is None:
            target_channel = ctx.channel

        # Update database
        self.db.Setting("enabled", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None) \
            .change(None)

        target_str = target_channel.mention
        await ctx.send(f":speaker: {target_str.capitalize()} has been un-blacklisted.")

    @extensions.command(name="mute", category="settings", opposite="unmute",
                        brief="Mute a user from using the bot.",
                        usage="[user] [**]",
                        emoji=":mute:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_mute(self, ctx: commands.Context, target_user: discord.User, target_channel: SettingsChannelConverter = "ask"):
        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(ctx, f"Do you mute {target_user.mention} in this channel or server wide?")

        # Update database
        self.db.Setting("muted_users", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None) \
            .push(target_user.id)

        target_channel_str = 'server wide' if not target_channel else f'in {target_channel.mention}'
        await ctx.send(f":mute: {target_user.mention} has been muted {target_channel_str}.")

    @extensions.command(name="unmute", category="settings",
                        brief="Unmute a user from using the bot.",
                        usage="[user] [**]",
                        emoji=":speaker:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_unmute(self, ctx: commands.Context, target_user: discord.User, target_channel: SettingsChannelConverter = "ask"):
        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(ctx, f"Do you unmute {target_user.mention} in this channel or server wide?")

        # Update database
        self.db.Setting("muted_users", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None) \
            .pop(target_user.id)

        target_channel_str = 'server wide' if not target_channel else f'in {target_channel.mention}'
        await ctx.send(f":speaker: {target_user.mention} has been unmuted {target_channel_str}.")

    @commands.command(name="update", aliases=["u"])
    @commands.check(check_if_bot_admin)
    async def command_update(self, ctx: commands.Context):
        await ctx.send("Updating...")
        self.setup_smiley_emojis_dict()
        self.db.update_configurations()
        await ctx.send("Finished updating.")
