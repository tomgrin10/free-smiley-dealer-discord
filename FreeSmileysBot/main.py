import discord
from discord.ext import commands
from typing import Union
import asyncio
import json
import random
import time
import datetime
import urllib.parse
import pathlib
import requests
import furl

# Constants
MESSAGE_CHARACTER_LIMIT = 2000
CONFIG_FILENAME = "config.json"
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
DYNAMIC_DATA_FILENAME = "dynamic_data.json"
DEFAULT_SMILEY_SIZE = 150
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300
T0 = time.time()

# Load data
with open(CONFIG_FILENAME) as f:
    CONFIG = json.load(f)
with open(STATIC_DATA_FILENAME, 'r') as f:
    STATIC_DATA = json.load(f)
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}
if pathlib.Path(DYNAMIC_DATA_FILENAME).is_file():
    with open(DYNAMIC_DATA_FILENAME, 'r') as f:
        DYNAMIC_DATA = json.load(f)
else:
    with open(DYNAMIC_DATA_FILENAME, 'w') as f:
        DYNAMIC_DATA = {"sizes": {}}
        json.dump(DYNAMIC_DATA, f, indent=4)
DYNAMIC_DATA_LOCK = asyncio.Lock()

# Connect to discord
client: discord.Client = discord.Client()
bot: commands.Bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(STATIC_DATA["prefix"])
)
bot.remove_command("help")


# List all emojis in message
def emoji_lis(s: str) -> list:
    for c in s:
        if c in DISCORD_EMOJI_TO_CODE:
            yield c


def split_message_for_discord(content: str, divider: str = None):
    if divider is None:
        segments = content
    else:
        segments = [s + divider for s in content.split(divider)]

    messages = [""]
    for segment in segments:
        if len(messages[len(messages) - 1]) + len(segment) >= MESSAGE_CHARACTER_LIMIT:
            messages.append(segment)
        else:
            messages[len(messages) - 1] += segment

    return messages


def log(s: str):
    async def async_log(s: str):
        print(s)
        for segment in split_message_for_discord(s):
            await bot.get_channel(CONFIG["logs_channel"]).send(segment)
        
    asyncio.create_task(async_log(s))


def rand_color_image_url(url: str) -> str:
    return furl.furl(url).add({"hue": random.randint(-100, 100),
                               "saturation": random.randint(-100, 100),
                               "lightness": random.randint(-100, 100)}).url


def spookify_image_url(url: str, spook_value: int) -> str:
    max_values = {"contrast": 36, "shadows": random.choice([100, -65]), "saturation": -100, "lightness": -100}
    return furl.furl(url).add({k: round(v * spook_value) for k, v in max_values.items()})


def get_free_smiley_url(emoji_name: str, message: discord.Message, smiley_num: str = None, allow_surprise=False) -> Union[str, None]:
    # Iterate emojis in message
    for p_smileys in STATIC_DATA["smileys"]:
        if emoji_name not in p_smileys:
            continue

        # Get and format url
        dir_name = p_smileys[0]
        dir_url = f"{STATIC_DATA['base_url']}/{dir_name}"
        dir_json = json.loads(requests.get(f"{dir_url}?json=true").text)

        if smiley_num is None:
            # Get random smiley
            try:
                # If ralf than maybe golden
                if dir_name == "ralf":
                    if random.random() * 100 < STATIC_DATA["golden_ralf_chance"]:
                        file_name = "golden.png"
                        log(f"Golden ralf has appeared in `{message.guild}`")
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
        if str(message.guild.id) in DYNAMIC_DATA['sizes']:
            free_smiley_url += f"?scale.height={DYNAMIC_DATA['sizes'][str(message.guild.id)]}"
        else:
            free_smiley_url += f"?scale.height={DEFAULT_SMILEY_SIZE}"

        # Random surprises
        if allow_surprise and not file_name.endswith(".gif"):
            # Recolor rare smiley suprise
            if random.random() * 100 < STATIC_DATA["surprise_chance"]:
                free_smiley_url = rand_color_image_url(free_smiley_url)
                log(f"Surprise in `{message.guild}`")

            # Halloween spooker
            elif random.random * 100 < 50:
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


@bot.event
async def on_ready():
    await bot.change_presence(game=discord.Game(name=STATIC_DATA["game"]))
    log("Bot is ready.")
    log(f"{len(bot.guilds)} guilds:\n{[g.name for g in sorted(bot.guilds, key=lambda g: g.member_count, reverse=True)]}")


@bot.event
async def on_message(message: discord.Message):
    try:
        # Check if not myself
        if message.author == bot.user or message.author.bot:
            return

        for emoji in emoji_lis(message.content):
            url = get_free_smiley_url(DISCORD_EMOJI_TO_CODE[emoji].replace(':', ''), message, allow_surprise=True)
            if url is not None:
                print(message.content + " detected.")

                # Create the embed
                embed = discord.Embed(title=random.choice(STATIC_DATA["titles"]))
                embed.set_image(url=url)
                await message.channel.send(content=f"{message.author.mention}", embed=embed)

                break

        await bot.process_commands(message)

    except Exception as e:
        message.channel.send(":x: **An error occurred.**")
        log(f"Error: {e}")


@bot.command(name="help", aliases=["h"])
async def command_help(ctx: commands.Context):
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


@bot.command(name="smiley", aliases=["s"])
async def command_smiley(ctx: commands.Context, emoji_name: str, smiley_num: str = None):
    url = get_free_smiley_url(emoji_name, ctx.message, smiley_num=smiley_num)
    if url is not None:
        print(ctx.message.content + " detected.")
        await ctx.send(url)
    else:
        await ctx.send(":x: **Smiley not found.**")


@bot.command(name="size", aliases=["height"])
async def command_size(ctx: commands.Context, size: str):
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
    async with DYNAMIC_DATA_LOCK:
        with open(DYNAMIC_DATA_FILENAME, 'w') as f:
            # Change size and save in file
            DYNAMIC_DATA["sizes"][str(ctx.guild.id)] = size
            json.dump(DYNAMIC_DATA, f, indent=4)

    log(f"Size changed to {size} in {ctx.message.guild}.")
    await ctx.send(f":white_check_mark: Size changed to {size}.")


@bot.command(name="invite", aliases=["inv"])
async def command_invite(ctx):
    if "invite" in CONFIG and CONFIG["invite"] is not None:
        await ctx.send(CONFIG["invite"])


@bot.command(name="support")
async def command_support(ctx):
    if "support" in CONFIG and CONFIG["support"] is not None:
        await ctx.send(CONFIG["support"])

    
@bot.command(name="uptime")
async def command_uptime(ctx):
    delta = datetime.timedelta(seconds=time.time() - T0)
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    mins, secs = divmod(rem, 60)
    await ctx.send(f"{days}d {hours}h {mins}m {secs}s")


@bot.command(name="log")
async def command_log(ctx, *, to_log):
    shortcuts = {
        "len": "len(bot.guilds)",
        "names": "[g.name for g in sorted(bot.guilds, key=lambda g: g.member_count, reverse=True)]",
    }

    if to_log in shortcuts:
        to_log = shortcuts[to_log]

    if ctx.author.id == 190224152978915329:
        log(f"{eval(to_log)}")


# Reload data every once in a while
async def reload_data_continuously():
    global STATIC_DATA, DISCORD_CODE_TO_EMOJI, DISCORD_EMOJI_TO_CODE
    await bot.wait_until_ready()
    while True:
        sleep_task = asyncio.create_task(asyncio.sleep(60))
        try:
            t0 = time.time()

            with open(STATIC_DATA_FILENAME, 'r') as f:
                STATIC_DATA = json.load(f)

            print(f"Reloaded data in {int(round((time.time() - t0) * 1000))} ms.")
        finally:
            await sleep_task


bot.loop.create_task(reload_data_continuously())
bot.run(CONFIG["token"])
