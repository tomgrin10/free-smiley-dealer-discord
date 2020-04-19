from __future__ import annotations

import asyncio
import copy
import itertools
import json
import logging
import random
import re
from typing import *

import discord
import emoji
from discord.ext import commands

import extensions
import utils
from database import Database, is_enabled, author_not_muted
from .converters import SettingsDefaultConverter, SettingsChannelConverter

# Constants
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}

logger = logging.getLogger(__name__)


def iterate_emojis_in_string(string: str) -> Iterator[str]:
    """
    List all emojis in a string.
    """
    return (d['emoji'] for d in emoji.emoji_lis(string))


async def settings_ask_channel_or_server(
        ctx: commands.Context,
        msg_content: str) -> Union[Type[discord.Guild], Type[discord.TextChannel]]:
    emojis_dict = {discord.Guild: "🇸", discord.TextChannel: "🇨"}

    msg_content = msg_content.replace("channel", f"{emojis_dict[discord.TextChannel]}hannel").replace(
        "server", f"{emojis_dict[discord.Guild]}erver")
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


def check_if_bot_admin(ctx: commands.Context):
    return ctx.author.id in ctx.bot.db.config["admin_users_id"]


def split_smiley_emoji_name_into_parts(smiley_emoji_name: str) -> Optional[Tuple[str, int]]:
    """
    Split smiley emoji name into its two core parts: the name and the index.
    'smiley_12' -> ('smiley', 12)
    Returns None if the name is invalid.
    :param smiley_emoji_name: The full name of the smiley emoji.
    :return: The core parts of the smiley emoji's name.
    """
    match = re.search(r"(\S*)_(\d+)", smiley_emoji_name)
    if match:
        parts = match.groups()
        return parts[0], int(parts[1])


class FreeSmileyDealerCog(commands.Cog):
    def __init__(self, bot: extensions.BasicBot, db: Database):
        global cog
        cog = self
        self.bot = bot

        self.db = db
        self.smiley_emojis_dict = dict()

        self.bot.remove_command("help")

    def setup_smiley_emojis_dict(self):
        """
        Set up dictionary of smiley emojis.
        """
        emoji_guilds = (self.bot.get_guild(int(id)) for id in self.db.config["emoji_guilds_id"])
        all_smiley_emojis: Generator[discord.Emoji] = sum((guild.emojis for guild in emoji_guilds), tuple())

        counter = 0
        for smiley_emoji, counter in zip(all_smiley_emojis, itertools.count(1)):
            smiley_name_parts = split_smiley_emoji_name_into_parts(smiley_emoji.name)
            if smiley_name_parts is None:
                continue

            smiley_name, _ = smiley_name_parts
            self.smiley_emojis_dict.setdefault(smiley_name, []).append(smiley_emoji)

        logger.info(f"Detected {counter} smiley emojis.")

    @commands.Cog.listener()
    async def on_ready(self):
        self.setup_smiley_emojis_dict()

    @commands.Cog.listener()
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
            pass

        # Error while executing a command
        elif isinstance(error, commands.CommandInvokeError) or __debug__:
            try:
                await ctx.send(format("An error has occurred."))
            except discord.Forbidden:
                pass
            raise error

    def get_emoji_name_from_unicode(self, emoji_unicode: str) -> str:
        if emoji_unicode in DISCORD_EMOJI_TO_CODE:
            emoji_name = DISCORD_EMOJI_TO_CODE[emoji_unicode]
        else:
            emoji_name = emoji.UNICODE_EMOJI[emoji_unicode]

        return emoji_name.replace(':', '')

    def get_smiley_name(self, emoji_name: str) -> str:
        # Iterate emojis in data
        for emoji_names in self.db.static_data["smileys"]:
            if emoji_name in emoji_names:
                return emoji_names[0]

        return emoji_name

    def get_smiley_reaction_emoji(self, emoji_name: str) -> Optional[discord.Emoji]:
        # Get smiley name from emoji name
        smiley_name = self.get_smiley_name(emoji_name)
        if smiley_name not in self.smiley_emojis_dict:
            return

        emojis = self.smiley_emojis_dict[smiley_name]
        if not emojis:
            return

        return random.choice(emojis)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Check if message executes command
        ctx: commands.Context = await self.bot.get_context(message)
        if not ctx.valid:
            # Invoke command to answer with appropriate smiley
            new_message = copy.copy(message)
            new_message.content = message.content
            new_ctx: commands.Context = await self.bot.get_context(new_message)
            command: commands.Command = self.bot.get_command("_on_message")
            new_ctx.command = command
            await self.bot.invoke(new_ctx)

    async def friday(self, ctx: commands.Context):
        if 'friday' in ctx.message.content.lower():
            if utils.chance(25):
                friday_emoji = random.choice(self.smiley_emojis_dict['friday'])

                # Regular mode
                if not self.db.Setting("lite_mode", ctx.guild.id, ctx.channel.id).read():
                    await self.send_smiley_emojis(ctx, [friday_emoji], add_title=False)

                # Lite mode
                else:
                    await self.react_with_smileys(ctx, [friday_emoji])

    async def send_smiley_emojis(
            self,
            ctx: commands.Context,
            emojis: Sequence[discord.Emoji],
            *, add_title=True):
        """
        Send smiley emojis with a title (not lite-mode).
        """
        title = random.choice(self.db.static_data['titles'])
        if add_title:
            await ctx.send(f"{ctx.author.mention} {title}")
        await ctx.send(' '.join(str(emoji) for emoji in emojis))

    async def react_with_smileys(self, ctx: commands.Context, emojis: Sequence[discord.Emoji]):
        """
        React with smiley emojis (lite-mode).
        """
        for emoji in emojis:
            await ctx.message.add_reaction(emoji)

    @extensions.command(name="_on_message", hidden=True)
    @commands.guild_only()
    @is_enabled()
    @author_not_muted()
    async def command__on_message(self, ctx: commands.Context, *, message_content):
        # Check if not myself or user not a bot
        if ctx.author == self.bot.user or ctx.author.bot:
            return

        smiley_names_generator = utils.iter_unique_values((
            self.get_smiley_name(self.get_emoji_name_from_unicode(emoji_unicode))
            for emoji_unicode in iterate_emojis_in_string(message_content)))

        smiley_emojis_generator = (
            self.get_smiley_reaction_emoji(smiley_name)
            for smiley_name in smiley_names_generator)

        smiley_emojis = list(
            itertools.islice(
                (smiley_emoji for smiley_emoji in smiley_emojis_generator if smiley_emoji),
                self.db.Setting("max_smileys", ctx.guild.id, ctx.channel.id).read()))

        # Check if there any emojis in message
        if not smiley_emojis:
            await self.friday(ctx)
            return

        # Regular mode
        if not self.db.Setting("lite_mode", ctx.guild.id, ctx.channel.id).read():
            await self.send_smiley_emojis(ctx, smiley_emojis)

        # Lite mode
        else:
            await self.react_with_smileys(ctx, smiley_emojis)

    @extensions.command(name="help", aliases=["h"])
    async def command_help(self, ctx: commands.Context, command: extensions.CommandConverter = None):
        def command_to_embed(command: extensions.Command, embed: discord.Embed = None, *,
                             long: bool = False) -> discord.Embed:
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
            command_call = f"{self.bot.db.config['prefix']}{sorted([command.name] + command.aliases, key=len)[0]}"
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
        help_message = (
            f":heart: -> {heart_emoji} If you use paid smileys (emojis) in your message, I will correct you.\n"
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
            command_names=("litemode", "maxsmileys", "blacklist", "mute")))

        await ctx.author.send(":+1: **Upvote me!** <https://discordbots.org/bot/475418097990500362/vote>\n"
                              f"**Join my server!** {self.bot.db.config['support_guild_url']}\n"
                              f"**Donate to keep the bot alive!** {self.bot.db.config['donate_url']}")

    @extensions.command(name="litemode", aliases=["lite"], category="settings",
                        brief="Litemode is a less spammy way to correct people.\nInstead of sending an image I will react with the smiley.",
                        usage="[on/off | *default*] [**]")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_litemode(self, ctx: commands.Context,
                               mode: Union[SettingsDefaultConverter, bool],
                               target_channel: SettingsChannelConverter = "ask"):
        def on_off(b: bool):
            return "on" if b else "off"

        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you want to turn lite mode {on_off(mode)} for the channel or the server default?")

        # Update database
        self.db.Setting("lite_mode", guild_id=ctx.guild.id,
                        channel_id=target_channel.id if target_channel else None) \
            .change(mode)

        # Send confirmation
        target_str = 'server default' if not target_channel else target_channel.mention
        await ctx.send(f":white_check_mark: {target_str.capitalize()} lite mode " +
                       (f"turned `{on_off(mode)}`." if mode is not None else f"returned to " +
                                                                             (
                                                                                 f"server default `{on_off(self.db.Setting('lite_mode', ctx.guild.id).read())}`." if target_channel else
                                                                                 f"global default `{on_off(self.db.get_global_default_setting('lite_mode'))}`.")))

    @extensions.command(name="maxsmileys", aliases=["max"], category="settings",
                        brief="Change the maximum count of smileys I will react to. (Default is 5)",
                        usage="[number | *default*] [**]")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_max_smileys(self, ctx: commands.Context,
                                  max_smileys_count: Union[SettingsDefaultConverter, int],
                                  target_channel: SettingsChannelConverter = "ask"):
        if not (1 <= max_smileys_count <= 20):
            raise commands.BadArgument("Max smileys count needs to be between 1-20.")

        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you want to change the max smileys count for the channel or the server default?")

            # Update database
            self.db.Setting("max_smileys", guild_id=ctx.guild.id,
                            channel_id=target_channel.id if target_channel else None) \
                .change(max_smileys_count)

            # Send confirmation
            target_str = 'server default' if not target_channel else target_channel.mention
            await ctx.send(f":white_check_mark: {target_str.capitalize()} max smileys count " +
                           (
                               f"changed to `{max_smileys_count}`." if max_smileys_count is not None else f"returned to " +
                                                                                                          (
                                                                                                              f"server default `{self.db.Setting('max_smileys', ctx.guild.id).read()}`." if target_channel else
                                                                                                              f"global default `{self.db.get_global_default_setting('max_smileys')}`.")))

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
        self.db.Setting("enabled", guild_id=ctx.guild.id,
                        channel_id=target_channel.id if target_channel else None) \
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
        self.db.Setting("enabled", guild_id=ctx.guild.id,
                        channel_id=target_channel.id if target_channel else None) \
            .change(None)

        target_str = target_channel.mention
        await ctx.send(f":speaker: {target_str.capitalize()} has been un-blacklisted.")

    @extensions.command(name="mute", category="settings", opposite="unmute",
                        brief="Mute a user from using the bot.",
                        usage="[user] [**]",
                        emoji=":mute:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_mute(self, ctx: commands.Context, target_user: discord.User,
                           target_channel: SettingsChannelConverter = "ask"):
        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you mute {target_user.mention} in this channel or server wide?")

        # Update database
        self.db.Setting("muted_users", guild_id=ctx.guild.id,
                        channel_id=target_channel.id if target_channel else None) \
            .push(target_user.id)

        target_channel_str = 'server wide' if not target_channel else f'in {target_channel.mention}'
        await ctx.send(f":mute: {target_user.mention} has been muted {target_channel_str}.")

    @extensions.command(name="unmute", category="settings",
                        brief="Unmute a user from using the bot.",
                        usage="[user] [**]",
                        emoji=":speaker:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_unmute(self, ctx: commands.Context, target_user: discord.User,
                             target_channel: SettingsChannelConverter = "ask"):
        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(ctx,
                                                                  f"Do you unmute {target_user.mention} in this channel or server wide?")

        # Update database
        self.db.Setting("muted_users", guild_id=ctx.guild.id,
                        channel_id=target_channel.id if target_channel else None) \
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

    @commands.command(name="name", aliases=['n'])
    @commands.check(check_if_bot_admin)
    async def command_name(self, ctx: commands.Context, emoji_unicode: str):
        emoji_name = emoji.UNICODE_EMOJI[emoji_unicode]
        await ctx.send(f"`{emoji_name}`")
