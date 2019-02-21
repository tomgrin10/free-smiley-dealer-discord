import asyncio
import copy
import datetime
import json
import logging
import random
import time
import urllib.parse
from typing import *

import discord
import furl
import pymongo
import requests
from discord.ext import commands

from .database import Database, is_enabled, author_not_muted
import extensions
from extensions import BasicBot

# Constants
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}


# List all emojis in message
def emoji_list(s: str) -> Iterator[str]:
    for c in s:
        if c in DISCORD_EMOJI_TO_CODE:
            yield c


def rand_color_image_url(url: str) -> str:
    return furl.furl(url).add({"hue": random.randint(-100, 100),
                               "saturation": random.randint(-100, 100),
                               "lightness": random.randint(-100, 100)}).url


def spookify_image_url(url: str, spook_value: float) -> str:
    max_values = {"contrast": 36, "shadows": random.choice([100, -65]), "saturation": -100, "lightness": -100}
    return furl.furl(url).add({k: round(v * spook_value) for k, v in max_values.items()})


def halloween_spook_value() -> float:
    curr_date = datetime.datetime.now()
    start_date = datetime.datetime(curr_date.year, 10, 15, 0)
    halloween_date = datetime.datetime(curr_date.year, 10, 31, 0)
    end_date = datetime.datetime(curr_date.year, 11, 2, 0)

    # Check if halloween time
    if start_date < curr_date < end_date:
        if curr_date < halloween_date:
            return (curr_date - start_date) / (halloween_date - start_date)
        else:
            return 1

    return 0


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


def to_size(arg: str) -> int:
    try:
        size = int(arg)
    except ValueError:
        raise commands.BadArgument("Size needs to be a number.")

    if size < MIN_SMILEY_SIZE or size > MAX_SMILEY_SIZE:
        raise extensions.BadSimilarArgument(f"Size must be between {MIN_SMILEY_SIZE} and {MAX_SMILEY_SIZE}.")

    return size


def to_emoji_name(arg: str) -> str:
    if arg in DISCORD_EMOJI_TO_CODE:
        return DISCORD_EMOJI_TO_CODE[arg].replace(':', '')

    raise commands.BadArgument("Not an emoji.")


class SettingsDefaultConverter(commands.Converter):
    def __init__(self, default_value=None):
        self.default_value = default_value

    async def convert(self, ctx, arg):
        if "default".startswith(arg):
            return self.default_value
        else:
            raise commands.BadArgument("Not default.")


class SettingsChannelConverter(commands.TextChannelConverter):
    async def convert(self, ctx: commands.Context, arg: str) -> Optional[discord.TextChannel]:
        """
        :return: The target channel of the command
                 None - If no channel given, guild default
        """
        if "channel".startswith(arg):
            return ctx.channel
        if "server".startswith(arg) or "guild".startswith(arg):
            return None

        return await super().convert(ctx, arg)


def get_cooldown(message: discord.Message) -> commands.Cooldown:
    global cog

    rate, per = cog.db.Setting("cooldown", message.guild.id, message.channel.id).read()
    return commands.Cooldown(rate, per, commands.BucketType.channel)


class FreeSmileyDealerCog:
    def __init__(self, bot: BasicBot):
        global cog
        cog = self
        self.bot = bot

        self.static_data_filename = STATIC_DATA_FILENAME
        with open(STATIC_DATA_FILENAME, 'r') as f:
            self.static_data = json.load(f)

        self.db = Database(self.static_data)
        self.smiley_emojis = dict()

        self.bot.remove_command("help")
        self.bot.loop.create_task(self.reload_data_continuously())

    async def update_smiley_emojis(self):
        logging.info("Starting to setup emojis.\n0%")
        # Iterate emoji names
        last_completion_percent = 0
        for emoji_names, i in zip(self.static_data["smileys"], range(len(self.static_data["smileys"]))):
            # Get and format url
            dir_name = emoji_names[0]
            dir_url = f"{self.static_data['base_url']}/{dir_name}"
            dir_json = json.loads(requests.get(f"{dir_url}?json=true").text)

            if dir_json["files"]:
                self.smiley_emojis[dir_name] = []

            # Iterate smiley images
            for file_json in dir_json["files"]:
                file_name = file_json["name"]
                animated = ".gif" in file_name
                smiley_name = f"{dir_name}_{file_name.split('.')[0]}"

                # If no need to update or reaction emoji exists continue
                if discord.utils.get(self.bot.config_objects["emojis"], name=smiley_name):
                    continue

                r = requests.get(f"{self.static_data['base_url']}/{dir_name}/{file_name}?"
                                 f"h={extensions.EMOJI_PIXEL_SIZE}&w={extensions.EMOJI_PIXEL_SIZE}")

                def predicate(g: discord.Guild) -> bool:
                    return len(list(filter(lambda e: e.animated == animated, g.emojis))) < extensions.MAX_EMOJIS

                guild = next((g for g in self.bot.config_objects["emoji_guilds"] if predicate(g)), None)
                if not guild:
                    logging.exception("Not enough space for new emojis.")
                try:
                    await guild.create_custom_emoji(name=smiley_name, image=r.content)
                    logging.info(f"Uploaded emoji `{smiley_name}` to `{guild.name}`.")
                except discord.HTTPException:
                    logging.exception(f"Emoji {smiley_name} failed to upload.")

            # Print progress
            completion_percent = int(((i + 1) / len(self.static_data["smileys"])) * 100)
            if completion_percent >= last_completion_percent + 10:
                last_completion_percent += 10
                if completion_percent == 100:
                    logging.info("100%\nEmojis setup over.")
                else:
                    logging.info(f"{last_completion_percent}%")

    def setup_smiley_emojis_dict(self):
        for emoji_names in self.static_data["smileys"]:
            smiley_name = emoji_names[0]
            emojis = filter(lambda e: e.name.startswith(smiley_name), self.bot.config_objects["emojis"])
            self.smiley_emojis[smiley_name] = sorted(emojis, key=lambda e: e.name.split('_')[-1])

    async def on_ready(self):
        #if not __debug__:
        #    await self.update_smiley_emojis()
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
        elif isinstance(error, (commands.BadArgument,)):
            await ctx.send(format(error))

        elif isinstance(error, commands.BadUnionArgument):
            await ctx.send(format(error.errors[1]))

        # Error while executing a command
        if isinstance(error, commands.CommandInvokeError) or __debug__:
            logging.exception(error)
            await ctx.send(format("An error has occurred."))

    def get_smiley_name(self, emoji_name: str) -> Optional[str]:
        # Iterate emojis in data
        for emoji_names in self.static_data["smileys"]:
            if emoji_name in emoji_names:
                return emoji_names[0]

    def get_smiley_url(self, emoji_name: str, ctx: commands.Context = None, *,
                       smiley_num: Optional[int] = None, allow_surprise=False) -> Optional[str]:
        """
        Returns an image url of the matching smiley with given parameters
        :param emoji_name: Name of the emoji to convert from.
        :param ctx: The message object
        :param smiley_num: Specification of the smiley to get from the folder
        :param allow_surprise: Allow surprises on the smiley or not
        :return: The image url
        """
        # Get smiley name from emoji name
        dir_name = self.get_smiley_name(emoji_name)
        if not dir_name:
            return

        # Get and format url
        dir_url = f"{self.static_data['base_url']}/{dir_name}"
        dir_json = json.loads(requests.get(f"{dir_url}?json=true").text)

        if smiley_num is None:
            # Get random smiley
            try:
                file_name = random.choice(dir_json['files'])['name']
                # If regular smiley
            except IndexError:
                return
        else:
            # Get smiley from smiley number
            matches = list(filter(lambda file: str(smiley_num) in file["name"], dir_json["files"]))
            if len(matches) == 0:
                return
            file_name = matches[0]["name"]

        free_smiley_url = f"{dir_url}/{urllib.parse.quote(file_name)}"

        # Attach height parameter to url
        if ctx:
            free_smiley_url += f"?h={self.db.Setting('smiley_size', ctx.guild.id, ctx.channel.id).read()}"

        # Random surprises
        if allow_surprise and not file_name.endswith(".gif"):
            chance = random.random() * 100

            # Recolor rare smiley surprise
            if chance < self.static_data["surprise_chance"]:
                free_smiley_url = rand_color_image_url(free_smiley_url)

            # Halloween spooker
            elif chance < 50:
                spook_value = halloween_spook_value()
                if spook_value > 0:
                    free_smiley_url = spookify_image_url(free_smiley_url, spook_value)

        return free_smiley_url

    def get_smiley_reaction_emoji(self, emoji_name: str) -> Optional[discord.Emoji]:
        # Get smiley name from emoji name
        smiley_name = self.get_smiley_name(emoji_name)
        if not smiley_name:
            return

        return random.choice(self.smiley_emojis[smiley_name])

    async def on_message(self, message: discord.Message):
        # Check if not myself or user not a bot
        if message.author == self.bot.user or message.author.bot:
            return

        # Check if message executes command
        ctx: commands.Context = await self.bot.get_context(message)
        if not ctx.valid:
            # Get first emoji in message
            emoji = next(emoji_list(message.content), None)
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

        async def send_smiley_image():
            # Iterate every emoji in the message and try to get the free smiley
            url = self.get_smiley_url(emoji_name, ctx, allow_surprise=True)
            if url is not None:
                # Create the embed
                embed = discord.Embed(title=random.choice(self.static_data["titles"]))
                embed.set_image(url=url)

                await ctx.send(content=f"{ctx.author.mention}", embed=embed)

        async def send_smiley_emoji():
            emoji = self.get_smiley_reaction_emoji(emoji_name)
            if emoji:
                await ctx.send(f"{ctx.author.mention} {random.choice(self.static_data['titles'])}")
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
        heart_emoji = self.smiley_emojis["heart"][0]
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

    @extensions.command(name="smiley", aliases=["s"], category="commands",
                        brief="Sends the full-size version of the smiley.",
                        usage="[emoji]",
                        examples=[":grin:", "<:grin_1:520062574205730827>"],
                        enabled=False)
    @commands.guild_only()
    @commands.bot_has_permissions(send_messages=True)
    async def command_smiley(self, ctx: commands.Context, emoji_name: Union[to_emoji_name, discord.Emoji, str]):
        # Check if argument is an Emoji
        if isinstance(emoji_name, discord.Emoji):
            # Check if argument is official smiley emoji
            if emoji_name in {x for v in self.smiley_emojis.values() for x in v}:
                smiley_num = emoji_name.name.split('_')[-1]
                smiley_name = emoji_name.name.replace(f"_{smiley_num}", '')
            else:
                raise commands.BadArgument("Smiley not found.")
        else:
            smiley_name = self.get_smiley_name(emoji_name)
            if not smiley_name:
                raise commands.BadArgument("Smiley not found.")

            if len(self.smiley_emojis[smiley_name]) == 1:
                smiley_num = 1
            # Ask what smiley to send
            else:
                question_msg = await ctx.send("Choose smiley.")
                try:
                    emoji = await self.bot.ask_question(question_msg, ctx.author, self.smiley_emojis[smiley_name], timeout=30)
                except asyncio.TimeoutError:
                    raise commands.BadArgument("Operation cancelled.")
                finally:
                    await question_msg.delete()
                smiley_num = int(emoji.name.split('_')[-1])

        url = self.get_smiley_url(smiley_name, smiley_num=smiley_num)
        if url is not None:
            await ctx.send(url)

    @extensions.command(name="size", category="settings",
                        brief="Change the size of the smiley image when correcting.",
                        usage="[pixels|*default*] [**]",
                        enable=False)
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def command_size(self, ctx: commands.Context,
                           size: Union[SettingsDefaultConverter, to_size], target_channel: SettingsChannelConverter = "ask"):
        if target_channel == "ask":
            # Ask user if he wants change to server or channel
            target_channel = await settings_ask_channel_or_server(ctx, "Do you want to change the channel smiley size or the server default?")

        # Update database
        self.db.Setting("smiley_size", guild_id=ctx.guild.id, channel_id=target_channel.id if target_channel else None)\
            .change(size)

        # Send confirmation
        target_str = 'server default' if not target_channel else target_channel.mention
        await ctx.send(f":white_check_mark: {target_str.capitalize()} smiley size " +
                       (f"changed to `{size}`." if size else f"returned to " +
                        (f"server default `{self.db.Setting('smiley_size', ctx.guild.id).read()}`." if target_channel else
                         f"global default `{self.db.get_global_default_setting('smiley_size')}`.")))

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

    # Reload data every once in a while
    async def reload_data_continuously(self):
        await self.bot.wait_until_ready()
        while True:
            sleep_task = asyncio.create_task(asyncio.sleep(60))
            try:
                t0 = time.time()

                with open(STATIC_DATA_FILENAME, 'r') as f:
                    self.static_data = json.load(f)

                print(f"Reloaded data in {int(round((time.time() - t0) * 1000))} ms.")
            finally:
                await sleep_task

