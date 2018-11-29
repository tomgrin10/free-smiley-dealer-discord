import asyncio
import datetime
import json
import logging
import pathlib
import random
import time
import urllib.parse
from typing import *

import discord
import furl
import pymongo
import requests
from discord.ext import commands

import extensions
from extensions import BasicBot

# Constants
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300
T0 = time.time()

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}


# List all emojis in message
def emoji_list(s: str) -> Iterable[str]:
    for c in s:
        if c in DISCORD_EMOJI_TO_CODE:
            yield c


def rand_color_image_url(url: str) -> str:
    return furl.furl(url).add({"hue": random.randint(-100, 100),
                               "saturation": random.randint(-100, 100),
                               "lightness": random.randint(-100, 100)}).url


def spookify_image_url(url: str, spook_value: int) -> str:
    max_values = {"contrast": 36, "shadows": random.choice([100, -65]), "saturation": -100, "lightness": -100}
    return furl.furl(url).add({k: round(v * spook_value) for k, v in max_values.items()})


def to_size(arg: str) -> Optional[int]:
    if "default".startswith(arg):
        return None

    try:
        size = int(arg)
    except ValueError:
        raise commands.BadArgument(":x: **Size needs to be a number.**")

    if size < MIN_SMILEY_SIZE or size > MAX_SMILEY_SIZE:
        raise extensions.BadSimilarArgument(f":x: **Size must be between {MIN_SMILEY_SIZE} and {MAX_SMILEY_SIZE}.**")

    return size


class FreeSmileyDealerCog:
    class Database:
        """
        Class representing a MongoDB database
        """
        def __init__(self, static_data):
            self._static_data = static_data

            self._client = pymongo.MongoClient(serverSelectionTimeoutMS=3)
            self._client.server_info()
            self._db = self._client["smiley_dealer"]
            self.data_fixer_upper()

        def get_default_setting(self, setting_name: str):
            return self._static_data["default_settings"][setting_name]

        def get_setting(self, setting_name: str, guild_id: Optional[int] = None, channel_id: Optional[int] = None):
            """
            Gets channel-specific/guild-specific or global default setting by name
            :param setting_name: Name of the setting
            :return: The setting value
            """
            def get_setting_from_database():
                if not guild_id:
                    return

                guild_doc = self._db["guilds"].find_one({"_id": str(guild_id)})

                # If guild has no document at all
                if not guild_doc:
                    return None

                # Try to get channel setting
                if channel_id:
                    try:
                        return guild_doc["settings"][str(channel_id)][setting_name]
                    except KeyError:
                        pass

                # Try to get default server setting
                try:
                    return guild_doc["settings"]['default'][setting_name]
                except KeyError:
                    pass

                return None

            # Try to get setting from database and return it if found
            setting_value = get_setting_from_database()
            if setting_value:
                return setting_value

            # There wasn't a setting so return global default
            return self.get_default_setting(setting_name)

        def change_setting_to_default(self, setting_name: str, guild_id: int, channel_id: Optional[int] = None):
            self._db["guilds"].update_one(
                {"_id": str(guild_id)},
                {"$unset":
                    {f"settings.{str(channel_id) if channel_id else 'default'}.{setting_name}": ""}})

        def change_setting(self, setting_name: str, guild_id: int, setting_value: Any = None, channel_id: Optional[int] = None):
            if setting_value is None:
                self.change_setting_to_default(setting_name, guild_id, channel_id)
                return

            # Change the value of the setting
            self._db["guilds"].update_one(
                {"_id": str(guild_id)},
                {"$set":
                    {f"settings.{str(channel_id) if channel_id else 'default'}.{setting_name}": setting_value}},
                upsert=True)

        def data_fixer_upper(self):
            path = pathlib.Path("dynamic_data.json")
            if path.is_file():
                with path.open() as f:
                    data = json.load(f)

                for guild_id, size in data["sizes"].items():
                    self._db["guilds"].update_one({"_id": str(guild_id)}, {"$set": {"settings.default.smiley_size": size}}, upsert=True)

                path.unlink()
                logging.info("Data has been *Fixer Upper*ed")

    def __init__(self, bot: BasicBot):
        self.bot = bot

        self.static_data_filename = STATIC_DATA_FILENAME
        with open(STATIC_DATA_FILENAME, 'r') as f:
            self.static_data = json.load(f)

        self.db = FreeSmileyDealerCog.Database(self.static_data)

        self.bot.remove_command("help")
        self.bot.loop.create_task(self.reload_data_continuously())

    def get_free_smiley_url(self, emoji_name: str, message: discord.Message, smiley_num: str = None,
                            allow_surprise=False) -> Optional[str]:

        """
        Returns an image url of the matching smiley with given parameters
        :param emoji_name: Name of the emoji to convert from.
        :param message: The message object
        :param smiley_num: Specification of the smiley to get from the folder
        :param allow_surprise: Allow surprises on the smiley or not
        :return: The image url
        """
        # Iterate emojis in message
        for p_smileys in self.static_data["smileys"]:
            if emoji_name not in p_smileys:
                continue

            # Get and format url
            dir_name = p_smileys[0]
            dir_url = f"{self.static_data['base_url']}/{dir_name}"
            dir_json = json.loads(requests.get(f"{dir_url}?json=true").text)

            if smiley_num is None:
                # Get random smiley
                try:
                    # If ralf than maybe golden
                    if dir_name == "ralf":
                        if random.random() * 100 < self.static_data["golden_ralf_chance"]:
                            file_name = "golden.png"
                            logging.info(f"Golden ralf has appeared in `{message.guild}`")
                        else:
                            file_name = "regular.png"
                    # If regular smiley
                    else:
                        file_name = random.choice(dir_json['files'])['name']
                except IndexError:
                    return
            else:
                # Get smiley from smiley number
                matches = list(filter(lambda file: smiley_num in file["name"], dir_json["files"]))
                if len(matches) == 0:
                    return
                file_name = matches[0]["name"]

            free_smiley_url = f"{dir_url}/{urllib.parse.quote(file_name)}"

            # Attach height parameter to url
            free_smiley_url += f"?scale.height={self.db.get_setting('smiley_size', message.guild.id, message.channel.id)}"

            # Random surprises
            if allow_surprise and not file_name.endswith(".gif"):
                # Recolor rare smiley surprise
                if random.random() * 100 < self.static_data["surprise_chance"]:
                    free_smiley_url = rand_color_image_url(free_smiley_url)
                    logging.info(f"Surprise in `{message.guild}`")

                # Halloween spooker
                elif random.random() * 100 < 50:
                    curr_date = datetime.datetime.now()
                    start_date = datetime.datetime(curr_date.year, 10, 15, 0)
                    halloween_date = datetime.datetime(curr_date.year, 10, 31, 0)
                    end_date = datetime.datetime(curr_date.year, 11, 2, 0)

                    # Check if halloween time
                    if start_date < curr_date < end_date:
                        if curr_date < halloween_date:
                            spook_value = (curr_date - start_date) / (halloween_date - start_date)
                        else:
                            spook_value = 1
                        free_smiley_url = spookify_image_url(free_smiley_url, spook_value)

            return free_smiley_url

    async def on_error(self):
        logging.exception("")

    async def on_ready(self):
        await self.bot.change_presence(activity=discord.Game(self.static_data["game"]))
        logging.info("Bot is ready.")
        logging.info(f"{len(self.bot.guilds)} guilds:\n{[g.name for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)]}")

    async def on_message(self, message: discord.Message):
        try:
            # Check if not myself
            if message.author == self.bot.user or message.author.bot:
                return
            # Check if not a dm
            if not message.guild:
                return
            # Check if I can write
            if not message.guild.me.permissions_in(message.channel).send_messages:
                return

            # Iterate every emoji in the message and try to get the free smiley
            for emoji in emoji_list(message.content):
                url = self.get_free_smiley_url(DISCORD_EMOJI_TO_CODE[emoji].replace(':', ''), message, allow_surprise=True)
                if url is not None:
                    # Create the embed
                    embed = discord.Embed(title=random.choice(self.static_data["titles"]))
                    embed.set_image(url=url)

                    await message.channel.send(content=f"{message.author.mention}", embed=embed)
                    break

        except Exception as e:
            message.channel.send(":x: **An error occurred.**")
            logging.exception("")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        to_send = (commands.BadArgument,)
        for err_type in to_send:
            if isinstance(error, err_type):
                await ctx.send(error)
                return

        if isinstance(error, commands.MissingPermissions):
            perm = error.missing_perms[0].replace('_', ' ').replace('guild', 'server').title()
            await ctx.send(f":x: **This command requires you to have `{perm}` permission to use it.**")

    @commands.command(name="help", aliases=["h"])
    async def command_help(self, ctx: commands.Context):
        help_message = """
:joy: -> <:SmileyJoy:514101595609235456> If you use paid smileys (emojis) in your message, I will correct you.
Type `:joy:` to try it out!

:scroll: For more commands look at your private messages."""
        await ctx.send(help_message)
        content = """
If you use **paid smileys (emojis)** in your message, I will correct you.
**Try it out!** Type `:joy:`"""
        embed = discord.Embed(title=":information_source: Commands - s!", color=0xf3f702)
        embed.add_field(name=":red_circle: smiley/s", value="""
If you just want to get **free smileys** without using paid smileys.
**Format:** `s!s <name> <number(optional)>`
**Examples:** `s!s grin`, `s!s cry 2`""")
        embed.add_field(name=":red_circle: size/height", value="""
Sets the size of the smileys. (default:`150`) (between `40-300`)
**Format:** `s!size <size>`
**Example:** `s!size 200`""")
        embed.add_field(name=":red_circle: invite/inv", value="""
Invite me to your guild!""")
        embed.add_field(name=":red_circle: support", value="""
Come to my support guild for help or suggestions!""")

        await ctx.author.send(content, embed=embed)

    @commands.command(name="smiley", aliases=["s"])
    async def command_smiley(self, ctx: commands.Context, emoji_name: str, smiley_num: Optional[str] = None):
        url = self.get_free_smiley_url(emoji_name.replace(':', ''), ctx.message, smiley_num=smiley_num)
        if url is not None:
            await ctx.send(url)
        else:
            await ctx.send(":x: **Smiley not found.**")

    @commands.command(name="size", aliases=["height"])
    @commands.has_permissions(manage_channels=True)
    async def command_size(self, ctx: commands.Context, size: to_size):
        server_emoji = "🇸"
        channel_emoji = "🇨"

        # Ask user if he wants change to server or channel
        question_msg: discord.Message = await ctx.send(f"Do you want to change the {channel_emoji}hannel smiley size or the {server_emoji}erver default?")
        try:
            answer_emoji = str((await self.bot.ask_question(question_msg, ctx.author, reactions=(channel_emoji, server_emoji), timeout=20)).emoji)
        except asyncio.TimeoutError:
            await question_msg.delete()
            await ctx.send(":x: **Operation cancelled.**")
            return
        await question_msg.delete()
        channel_id = ctx.channel.id if answer_emoji == channel_emoji else None

        # Update database
        self.db.change_setting("smiley_size", ctx.guild.id, size, channel_id)

        # Send confirmation
        await ctx.send(f":white_check_mark: {'Channel' if channel_id else 'Server default'} smiley size " +
                       (f"changed to `{size}`." if size else f"returned to " +
                        (f"server default `{self.db.get_setting('smiley_size', ctx.guild.id)}`." if channel_id else
                         f"global default `{self.db.get_default_setting('smiley_size')}`.")))

    @commands.command(name="invite", aliases=["inv"])
    async def command_invite(self, ctx):
        if "invite" in self.bot.config and self.bot.config["invite"] is not None:
            await ctx.send(self.bot.config["invite"])

    @commands.command(name="support")
    async def command_support(self, ctx):
        if "support" in self.bot.config and self.bot.config["support"] is not None:
            await ctx.send(self.bot.config["support"])

    @commands.command(name="uptime")
    async def command_uptime(self, ctx):
        delta = datetime.timedelta(seconds=time.time() - T0)
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        mins, secs = divmod(rem, 60)
        await ctx.send(f"{days}d {hours}h {mins}m {secs}s")

    @commands.command(name="log")
    @commands.is_owner()
    async def command_log(self, ctx: commands.Context, *, to_log):

        shortcuts = {
            "len": "len(self.bot.guilds)",
            "names": "[g.name for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)]",
        }

        if to_log in shortcuts:
            to_log = shortcuts[to_log]

        logging.info(f"{ctx.message.content}:\n{eval(to_log)}")

    # Reload data every once in a while
    async def reload_data_continuously(self):
        global DISCORD_CODE_TO_EMOJI, DISCORD_EMOJI_TO_CODE
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

