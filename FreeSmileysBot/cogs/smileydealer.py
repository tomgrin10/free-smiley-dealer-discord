from typing import *
import asyncio
from contextlib import asynccontextmanager
import logging
import json
import random
import time
import datetime
import urllib.parse
import pathlib

import discord
from discord.ext import commands
import requests
import furl

from bot import BasicBot

# Constants
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
DYNAMIC_DATA_FILENAME = "dynamic_data.json"
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300
T0 = time.time()

# Load data
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}


def fix_data_structure(data: dict, template: dict):
    for key in template:
        if key not in data:
            data[key] = template[key]


# List all emojis in message
def emoji_lis(s: str) -> Iterable[str]:
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


class FreeSmileyDealerCog:
    def __init__(self, bot: BasicBot):
        self.bot = bot

        self.static_data_filename = STATIC_DATA_FILENAME
        with open(STATIC_DATA_FILENAME, 'r') as f:
            self.static_data = json.load(f)

        self.dynamic_data_filename = DYNAMIC_DATA_FILENAME
        # dynamic_data_template = {"sizes": {}, ""}
        if pathlib.Path(DYNAMIC_DATA_FILENAME).is_file():
            with open(DYNAMIC_DATA_FILENAME, 'r') as f:
                self.dynamic_data = json.load(f)
        else:
            with open(DYNAMIC_DATA_FILENAME, 'w') as f:
                self.dynamic_data = {"sizes": {}}
                json.dump(self.dynamic_data, f, indent=4)
        self._dynamic_data_lock = asyncio.Lock()

        self.bot.remove_command("help")
        self.bot.loop.create_task(self.reload_data_continuously())

    @asynccontextmanager
    async def save_dynamic_data(self):
        async with self._dynamic_data_lock:
            with open(DYNAMIC_DATA_FILENAME, 'w') as f:
                yield
                json.dump(self.dynamic_data, f, indent=4)

    def get_free_smiley_url(self, emoji_name: str, message: discord.Message, smiley_num: str = None,
                            allow_surprise=False) -> Union[str, None]:
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
                print(dir_json["files"])
                matches = list(filter(lambda file: smiley_num in file["name"], dir_json["files"]))
                if len(matches) == 0:
                    return
                file_name = matches[0]["name"]

            free_smiley_url = f"{dir_url}/{urllib.parse.quote(file_name)}"

            # Attach height parameter to url
            if str(message.guild.id) in self.dynamic_data['sizes']:
                free_smiley_url += f"?scale.height={self.dynamic_data['sizes'][str(message.guild.id)]}"
            else:
                free_smiley_url += f"?scale.height={self.static_data['default_smiley_size']}"

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

    async def on_error(self, event_method, *args, **kwargs):
        logging.exception("")

    async def on_ready(self):
        await self.bot.change_presence(game=discord.Game(name=self.static_data["game"]))
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

            for emoji in emoji_lis(message.content):
                url = self.get_free_smiley_url(DISCORD_EMOJI_TO_CODE[emoji].replace(':', ''), message, allow_surprise=True)
                if url is not None:
                    print(message.content + " detected.")

                    # Create the embed
                    embed = discord.Embed(title=random.choice(self.static_data["titles"]))
                    embed.set_image(url=url)
                    await message.channel.send(content=f"{message.author.mention}", embed=embed)

                    break

        except Exception as e:
            message.channel.send(":x: **An error occurred.**")
            logging.exception("")

    @commands.command(name="help", aliases=["h"])
    async def command_help(self, ctx: commands.Context):
        await ctx.send("""
If you use **paid smileys (emojis)** in your message, I will correct you.
**Try it out!** Type `:joy:`

For more epic commands look in your **private messages**!""")

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
    async def command_smiley(self, ctx: commands.Context, emoji_name: str, smiley_num: str = None):
        url = self.get_free_smiley_url(emoji_name, ctx.message, smiley_num=smiley_num)
        if url is not None:
            print(ctx.message.content + " detected.")
            await ctx.send(url)
        else:
            await ctx.send(":x: **Smiley not found.**")

    @commands.command(name="size", aliases=["height"])
    async def command_size(self, ctx: commands.Context, size: str):
        # Check for permissions
        if not ctx.author.guild_permissions.manage_channels:
            await ctx.send(":x: **This command requires you to have `Manage Channels` permission to use it.**")
            return

        # Validate size parameter
        try:
            size = int(size)
        except ValueError:
            await ctx.send(":x: **Invalid size.**")
            return

        if size < MIN_SMILEY_SIZE or size > MAX_SMILEY_SIZE:
            await ctx.send(f":x: **Size must be between {MIN_SMILEY_SIZE} and {MAX_SMILEY_SIZE}.**")
            return

        # Lock thread
        async with self.save_dynamic_data():
            self.dynamic_data["sizes"][str(ctx.guild.id)] = size

        logging.info(f"Size changed to {size} in {ctx.message.guild}.")
        await ctx.send(f":white_check_mark: Size changed to {size}.")

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
    async def command_log(self, ctx, *, to_log):
        shortcuts = {
            "len": "len(self.bot.guilds)",
            "names": "[g.name for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)]",
        }

        if to_log in shortcuts:
            to_log = shortcuts[to_log]

        if ctx.author.id == 190224152978915329:
            logging.info(f"{eval(to_log)}")

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


class LoggingHandler(logging.Handler):
    def __init__(self, bot: BasicBot):
        super().__init__()
        self.bot = bot

    def emit(self, record: logging.LogRecord):
        if self.bot.is_ready():
            self.bot.log(self.format(record))
