from __future__ import annotations

import asyncio
import copy
import enum
import json
import logging
import random
import re
from contextlib import suppress
from typing import (
    Type, Iterable, Optional, Dict, Iterator, Sequence, AsyncIterator, Union, Tuple, Any)

import discord
import emojis
import emojis.db
from aioitertools import islice, list as aiolist
from discord import Guild, Emoji
from discord.ext import commands
from emojis.emojis import EMOJI_TO_ALIAS

import extensions
from utils import chance, iter_unique_values, user_full_name
from database import Database, is_enabled, author_not_muted
from .converters import (
    SettingsDefaultConverter, SettingsChannelConverter,
    create_enum_converter, Default, SettingsAllConverter, All)

# Constants
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
REGEX_FIND_WORD_IN_MESSAGE = re.compile(r'\b{}\b', re.IGNORECASE)

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}

logger = logging.getLogger(__name__)


def format_error(msg) -> str:
    """Command error format for user."""
    return f":x: **{msg}**"


def format_settings_dict(
        global_settings: Dict[str, Any],
        guild_document: Optional[Dict[str, Any]],
        bot: extensions.BasicBot) -> discord.Embed:
    def format_channel_settings(settings: Dict[str, Any]):
        message = f""
        for key, value in settings.items():
            if key == 'muted_users':
                users = [
                    user_full_name(bot.get_user(user_id))
                    for user_id in value]
                message += f"{key}: {users}\n"
            elif key == 'mode':
                message += f"{key}: `{Mode(value).name}`\n"
            else:
                message += f"{key}: `{value}`\n"
        return message

    embed = discord.Embed()
    embed.add_field(
        name=':gear: Global Default',
        value=format_channel_settings(global_settings),
        inline=False)

    if guild_document:
        guild_document = guild_document['settings']
        if 'default' in guild_document:
            embed.add_field(
                name=':gear: Server Default',
                value=format_channel_settings(guild_document['default']),
                inline=False)
        for channel_id, settings in guild_document.items():
            if channel_id != "default" and settings:
                channel: discord.TextChannel = bot.get_channel(int(channel_id))
                embed.add_field(
                    name=channel.name,
                    value=format_channel_settings(settings),
                    inline=False)

    return embed


def iterate_emojis_in_string(string: str) -> Iterable[str]:
    """
    List all emojis in a string.
    """
    return emojis.iter(string)


async def settings_ask_channel_or_server(
        ctx: commands.Context,
        msg_content: str) -> Union[Type[discord.Guild], Type[discord.TextChannel]]:
    emojis_dict = {discord.Guild: "🇸", discord.TextChannel: "🇨"}

    msg_content = msg_content.replace("channel",
                                      f"{emojis_dict[discord.TextChannel]}hannel").replace(
        "server", f"{emojis_dict[discord.Guild]}erver")
    emojis = sorted(emojis_dict.values(), key=lambda e: msg_content.find(e))

    question_msg: discord.Message = await ctx.send(msg_content)
    try:
        answer_emoji = str(
            await ctx.bot.ask_question(
                question_msg,
                ctx.author,
                emojis=emojis,
                timeout=20))
    except asyncio.TimeoutError:
        raise commands.BadArgument("Operation cancelled.")
    finally:
        await question_msg.delete()

    question_result = {v: k for k, v in emojis_dict.items()}[answer_emoji]
    return None if question_result == discord.Guild else ctx.channel


class Mode(enum.IntEnum):
    simple = 0
    title = 1
    reaction = 2


async def ask_for_mode(ctx: commands.Context) -> Mode:
    emojis_dict = {
        Mode.simple: '🇸',
        Mode.title: '🇹',
        Mode.reaction: '🇷'
    }

    msg_content = (
        "Do you want the bot to :regional_indicator_s:imply send the smileys, "
        "add a :regional_indicator_t:itle while doing it, "
        "or just :regional_indicator_r:eact with them?")

    question_msg: discord.Message = await ctx.send(msg_content)
    try:
        answer_emoji = str(
            await ctx.bot.ask_question(
                question_msg,
                ctx.author,
                emojis=emojis_dict.values(),
                timeout=20))
    except asyncio.TimeoutError:
        raise commands.BadArgument("Operation cancelled.")
    finally:
        await question_msg.delete()

    question_result = {v: k for k, v in emojis_dict.items()}[answer_emoji]
    return question_result


def check_if_bot_admin(ctx: commands.Context):
    return ctx.author.id in ctx.bot.db.config["admin_users_id"]


def split_smiley_emoji_name_into_parts(smiley_emoji_name: str) -> Optional[
    Tuple[str, int]]:
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

    async def _get_all_smiley_emojis(self) -> AsyncIterator[Emoji]:
        emoji_guilds: Iterator[Guild] = (
            self.bot.get_guild(int(guild_id))
            for guild_id in self.db.config["emoji_guilds_id"]
            if self.bot.get_guild(int(guild_id))
        )

        for guild in emoji_guilds:
            for emoji_ in await guild.fetch_emojis():
                yield emoji_

    async def setup_smiley_emojis_dict(self):
        """
        Set up dictionary of smiley emojis.
        """
        new_smiley_emojis_dict = {}

        counter = 0
        async for smiley_emoji in self._get_all_smiley_emojis():
            smiley_name_parts = split_smiley_emoji_name_into_parts(smiley_emoji.name)
            if smiley_name_parts is None:
                continue

            smiley_name, _ = smiley_name_parts
            new_smiley_emojis_dict.setdefault(smiley_name, []).append(smiley_emoji)

            counter += 1

        self.smiley_emojis_dict = new_smiley_emojis_dict

        logger.info(f"Detected {counter} smiley emojis.")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.setup_smiley_emojis_dict()

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        with suppress(discord.Forbidden):
            # Missing permissions to run command
            if isinstance(error, commands.MissingPermissions):
                perm = error.missing_perms[0].replace('_', ' ').replace('guild',
                                                                        'server').title()
                await ctx.send(format_error(
                    f"This command requires you to have `{perm}` permission to use it."))

            # User gave bad arguments
            elif isinstance(error, (commands.BadArgument, commands.CommandNotFound)):
                await ctx.send(format_error(error))

            elif isinstance(error, commands.BadUnionArgument):
                await ctx.send(format_error(error.errors[1]))

            # Ignore error
            elif isinstance(error, commands.CheckFailure):
                pass

            # Error while executing a command
            elif isinstance(error, commands.CommandInvokeError):
                if isinstance(error.original, discord.Forbidden):
                    return

                await ctx.send(format_error("An error has occurred."))
                raise error

    def get_emoji_name_from_unicode(self, emoji_unicode: str) -> str:
        if emoji_unicode in DISCORD_EMOJI_TO_CODE:
            emoji_name: str = DISCORD_EMOJI_TO_CODE[emoji_unicode]
        else:
            emoji_name: str = EMOJI_TO_ALIAS[emoji_unicode]

        return emoji_name.replace(':', '').replace('-', '_')

    def get_smiley_name(self, emoji_name: str) -> str:
        """
        Get the name of the smiley from the name of the emoji.
        "calendar" -> "friday"
        "face_vomiting" -> "nauseated"
        :param emoji_name: Name of the emoji.
        :return: Name of the smiley (that is in smiley_emojis_dict)
        """
        # Iterate emojis in data
        for emoji_names in self.db.static_data["smileys"]:
            if emoji_name in emoji_names:
                return emoji_names[0]

        return emoji_name

    def get_smiley_reaction_emoji(self, emoji_name: str) -> Optional[discord.Emoji]:
        """
        Get the smiley emoji object from the original emoji name.
        "calendar" -> "friday" emoji object
        :param emoji_name: Name of the emoji.
        :return: Smiley emoji object, or None if not found.
        """
        # Get smiley name from emoji name
        smiley_name = self.get_smiley_name(emoji_name)
        if smiley_name not in self.smiley_emojis_dict:
            return

        emojis = self.smiley_emojis_dict[smiley_name]
        if not emojis:
            return

        return random.choice(emojis)

    def get_smiley_emoji_from_emoji(self, emoji_unicode: str) -> Optional[discord.Emoji]:
        emoji_name = self.get_emoji_name_from_unicode(emoji_unicode)
        return self.get_smiley_reaction_emoji(emoji_name)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Check if message executes command
        ctx: commands.Context = await self.bot.get_context(message)
        if not ctx.valid and ctx.message.content:
            # Invoke command to answer with appropriate smiley
            new_message = copy.copy(message)
            new_message.content = message.content
            new_ctx: commands.Context = await self.bot.get_context(new_message)
            command: commands.Command = self.bot.get_command("_on_message")
            new_ctx.command = command
            await self.bot.invoke(new_ctx)

    async def react_to_words(self, ctx: commands.Context):
        """
        React to words by chance.
        Example: If someone types out "FRIDAY", the bot will has a chance
         to reply with a friday smiley.
        """
        chances_dict_setting = self.db.Setting("random_reactions_chances")
        chances_dict: Optional[Dict[str, int]] = None

        random_reaction_words = (
            self.db.get_global_default_setting("random_reactions_chances").keys())

        smiley_emojis = []
        regex_pattern = '|'.join(fr'(?:\b{word}\b)' for word in random_reaction_words)
        reaction_words = (
            match.group().lower()
            for match in re.finditer(regex_pattern, ctx.message.content, re.IGNORECASE))

        for random_reaction_name in iter_unique_values(reaction_words):
            # Read random_reactions_chances setting if not read yet
            chances_dict = chances_dict or await chances_dict_setting.read()
            chances = chances_dict[random_reaction_name]

            if not chance(chances):
                continue

            smiley_emojis.append(self.get_smiley_reaction_emoji(random_reaction_name))

        if smiley_emojis:
            await self.send_smileys_based_on_mode(
                ctx,
                smiley_emojis,
                always_no_title=True)

    async def send_smiley_emojis(
            self,
            ctx: commands.Context,
            emojis: Iterable[discord.Emoji],
            *, add_title=True):
        """
        Send smiley emojis with a title (not lite-mode).
        """
        if add_title:
            title = random.choice(self.db.static_data['titles'])
            await ctx.send(f"{ctx.author.mention} {title}")

        await ctx.send(' '.join(str(emoji) for emoji in emojis))

    async def react_with_emojis(self, ctx: commands.Context,
                                emojis: Iterable[discord.Emoji]):
        """
        React with smiley emojis (lite-mode).
        """
        for emoji in emojis:
            await ctx.message.add_reaction(emoji)

    async def send_smileys_based_on_mode(
            self,
            ctx: commands.Context,
            smiley_emojis: Iterable[discord.Emoji],
            *, always_no_title: bool = False):
        """
        Send smileys based on mode in settings.
        :param ctx:
        :param smiley_emojis:
        :param always_no_title: Don't add titles, no matter what's the mode.
        """
        mode = await self.db.Setting("mode", ctx.guild.id, ctx.channel.id).read()

        # Reaction mode
        if mode == Mode.reaction:
            await self.react_with_emojis(ctx, smiley_emojis)

        else:
            # Simple mode (no titles)
            if mode == Mode.simple or always_no_title:
                await self.send_smiley_emojis(ctx, smiley_emojis, add_title=False)

            # Title mode
            else:  # mode == Mode.title
                await self.send_smiley_emojis(ctx, smiley_emojis)

    @extensions.command(name="_on_message", hidden=True)
    @commands.guild_only()
    @is_enabled()
    @author_not_muted()
    async def command__on_message(self, ctx: commands.Context, *, message_content):
        # Check if not myself or user not a bot
        if ctx.author == self.bot.user or ctx.author.bot:
            return

        smiley_names_generator = iter_unique_values((
            self.get_smiley_name(self.get_emoji_name_from_unicode(emoji_unicode))
            for emoji_unicode in iterate_emojis_in_string(message_content)))

        smiley_emojis_generator = (
            self.get_smiley_reaction_emoji(smiley_name)
            for smiley_name in smiley_names_generator)

        smiley_emojis = await aiolist(
            islice(
                (smiley_emoji for smiley_emoji in smiley_emojis_generator if
                 smiley_emoji),
                await self.db.Setting("max_smileys", ctx.guild.id,
                                      ctx.channel.id).read()))

        # Check if there any emojis in message
        if not smiley_emojis:
            await self.react_to_words(ctx)
            return

        await self.send_smileys_based_on_mode(ctx, smiley_emojis)

    @command__on_message.error
    async def command__on_message_error(self, ctx: commands.Context,
                                        error: commands.CommandError):
        # Raise on this error
        if isinstance(error, commands.CommandInvokeError):
            # Except when there's this error in it
            if isinstance(error.original, discord.Forbidden):
                return

            raise error

        return

    @extensions.command(name="help", aliases=["h"])
    async def command_help(self, ctx: commands.Context,
                           command: extensions.CommandConverter = None):
        def command_to_embed(command: extensions.Command, embed: discord.Embed = None, *,
                             long: bool = False) -> discord.Embed:
            """
            Add a field for the command in an embed or create an embed for the command.
            """

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
                embed.add_field(name=name, value=value,
                                inline=not (command.usage or command.help))
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
                        "**Example:** s!lite on channel",
            colour=0x7bb3b5,
            command_names=('settings', "mode", "maxsmileys", "blacklist", "mute")))

        await ctx.author.send(
            ":+1: **Upvote me!** <https://discordbots.org/bot/475418097990500362/vote>\n"
            f"**Join my server!** {self.bot.db.config['support_guild_url']}\n"
            f"**Donate to keep the bot alive!** {self.bot.db.config['donate_url']}")

    @extensions.command(
        name="mode", aliases=[], category="settings",
        brief="Change the bot's way of sending smileys. (default is `simple`)\n"
              "`simple` - Just send the smileys, without nonsense.\n"
              "`title` - Send the smileys with a nice title and a mention, just for you.\n"
              "`reaction` - React with the smileys, instead of sending them as a message!",
        usage="[mode | *default*] [**]")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_mode(
            self,
            ctx: commands.Context,
            mode: Optional[Union[
                Mode, create_enum_converter(Mode), SettingsDefaultConverter]] = None,
            target_channel: SettingsChannelConverter = "ask"):

        # Interactively ask mode
        if mode is None:
            mode = await ask_for_mode(ctx)

        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you want to change mode to `{mode.name.lower()}` for "
                f"the channel or the server default?")

        # Update database
        setting = self.db.Setting(
            "mode",
            guild_id=ctx.guild.id,
            channel_id=target_channel.id if target_channel else None)
        await setting.change(mode)

        # Send confirmation
        target_str = 'server default' if not target_channel else target_channel.mention
        confirmation = f":white_check_mark: {target_str.capitalize()} mode "
        if mode is not Default:
            confirmation += f"changed to `{mode.name.lower()}`."
        else:
            confirmation += f"returned to "
            if target_channel:
                server_default = Mode(await self.db.Setting('mode', ctx.guild.id).read())
                confirmation += f"server default `{server_default.name.lower()}`."
            else:
                global_default = Mode(await self.db.Setting('lite_mode').read())
                confirmation += f"global default `{global_default.name.lower()}`."

        await ctx.send(confirmation)

    @extensions.command(name="maxsmileys", aliases=["max"], category="settings",
                        brief="Change the maximum count of smileys I will react to. (default is 10)",
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
        await self.db.Setting("max_smileys", guild_id=ctx.guild.id,
                              channel_id=target_channel.id if target_channel else None) \
            .change(max_smileys_count)

        # Send confirmation
        target_str = 'server default' if not target_channel else target_channel.mention
        await ctx.send(
            f":white_check_mark: {target_str.capitalize()} max smileys count " +
            (
                f"changed to `{max_smileys_count}`." if max_smileys_count is not Default else f"returned to " +
                                                                                              (
                                                                                                  f"server default `{await self.db.Setting('max_smileys', ctx.guild.id).read()}`." if target_channel else
                                                                                                  f"global default `{self.db.get_global_default_setting('max_smileys')}`.")))

    @extensions.command(
        name="blacklist", aliases=["bl"], category="settings",
        opposite="whitelist",
        brief="Blacklist a channel from the bot.\n"
              "`s!bl all` makes all channels blacklisted by default.",
        usage="[*optional*: channel]",
        emoji=":mute:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_blacklist(
            self,
            ctx: commands.Context,
            target_channel: Union[discord.TextChannel, SettingsAllConverter] = None):
        if target_channel is None:
            target_channel = ctx.channel

        if target_channel is All:
            target_channel = None

        # Update database
        await self.db.Setting("enabled", guild_id=ctx.guild.id,
                              channel_id=target_channel.id if target_channel else None) \
            .change(False)

        if target_channel:
            target_str = f"{target_channel.mention} has"
        else:
            target_str = "All channels have"
        await ctx.send(f":mute: {target_str.capitalize()} been blacklisted.")

    @extensions.command(name="whitelist", aliases=["wl", "unblacklist"],
                        category="settings",
                        brief="Un-blacklist a channel from the bot.",
                        usage="[*optional*: channel]",
                        emoji=":speaker:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_whitelist(
            self,
            ctx: commands.Context,
            target_channel: Union[discord.TextChannel, SettingsAllConverter] = None):
        if target_channel is None:
            target_channel = ctx.channel

        if target_channel is All:
            target_channel = None

        # Update database
        await self.db.Setting("enabled", guild_id=ctx.guild.id,
                              channel_id=target_channel.id if target_channel else None) \
            .change(True)

        if target_channel:
            target_str = f"{target_channel.mention} has"
        else:
            target_str = "All channels have"
        await ctx.send(f":mute: {target_str.capitalize()} been un-blacklisted.")

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
                f"Do you mute {target_user.display_name} in this channel or server wide?")

        # Update database
        await self.db.Setting("muted_users", guild_id=ctx.guild.id,
                              channel_id=target_channel.id if target_channel else None) \
            .push(target_user.id)

        target_channel_str = 'server wide' if not target_channel else f'in {target_channel.mention}'
        await ctx.send(
            f":mute: {target_user.mention} has been muted {target_channel_str}.")

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
            target_channel = await settings_ask_channel_or_server(
                ctx,
                f"Do you unmute {target_user.display_name} in this channel or server wide?")

        # Update database
        await self.db.Setting("muted_users", guild_id=ctx.guild.id,
                              channel_id=target_channel.id if target_channel else None) \
            .pop(target_user.id)

        target_channel_str = 'server wide' if not target_channel else f'in {target_channel.mention}'
        await ctx.send(
            f":speaker: {target_user.mention} has been unmuted {target_channel_str}.")

    @extensions.command(name="settings", aliases=['config'], category="settings",
                        brief="Show the server's bot settings.",
                        usage="",
                        emoji=":gear:")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_settings(self, ctx: commands.Context):
        guild_document = await self.db.get_guild_document(ctx.guild.id)
        global_settings = self.db.static_data["default_settings"]
        embed = format_settings_dict(global_settings, guild_document, self.bot)
        await ctx.send(embed=embed)

    @commands.command(name="update", aliases=["u"])
    @commands.check(check_if_bot_admin)
    async def command_update(self, ctx: commands.Context):
        await ctx.send("Updating...")
        await self.db.update_configurations()
        await self.setup_smiley_emojis_dict()
        await ctx.send("Finished updating.")

    @commands.command(name="name", aliases=['n'])
    @commands.check(check_if_bot_admin)
    async def command_name(self, ctx: commands.Context, *, message_content: str):
        emojis_iter = iterate_emojis_in_string(message_content)
        emoji_names = ','.join(f'"{self.get_emoji_name_from_unicode(emoji)}"'
                               for emoji in emojis_iter)
        await ctx.send(f"`{emoji_names}`")

    @commands.command(name="category", aliases=[''])
    @commands.check(check_if_bot_admin)
    async def command_category(self, ctx: commands.Context):
        await ctx.send(str(emojis.db.get_categories()))

    @commands.command(name="create", aliases=['c'])
    @commands.check(check_if_bot_admin)
    async def command_create(self, ctx: commands.Context, *, category: str):
        category_emojis: Iterable[str] = (
            emoji.emoji for emoji in
            emojis.db.get_emojis_by_category(category))

        emojis_with_no_smiley = (
            emoji for emoji
            in category_emojis
            if self.get_smiley_emoji_from_emoji(emoji) is None
        )

        await ctx.send(' '.join(emojis_with_no_smiley))
