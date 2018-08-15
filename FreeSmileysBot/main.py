import discord
from discord.ext import commands
import asyncio
import json
import random
import time
import tldextract
import pathlib
import requests

# Constants
TOKEN_FILENAME = "token.json"
STATIC_DATA_FILENAME = "static_data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"
DYNAMIC_DATA_FILENAME = "dynamic_data.json"
DEFAULT_SMILEY_SIZE = 150
MIN_SMILEY_SIZE = 40
MAX_SMILEY_SIZE = 300

# Load data
with open(TOKEN_FILENAME) as f:
    TOKEN = json.load(f)["token"]
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


def format_sirv_smiley_url(url: str, server_id: str) -> str:
    if server_id in DYNAMIC_DATA['sizes']:
        return url + f"?scale.height={DYNAMIC_DATA['sizes'][server_id]}"
    else:
        return url + f"?scale.height={DEFAULT_SMILEY_SIZE}"


async def correct_smiley(emoji_names: list, message: discord.Message, do_mention: bool = True, do_title: bool = True):
    # Iterate emojis in message
    for emoji_name in emoji_names:
        for p_smileys in STATIC_DATA["smileys"]:
            if emoji_name not in p_smileys:
                continue

            print(message.content + " detected.")

            # Get parameters for embed
            title = random.choice(STATIC_DATA["titles"])
            dir_url = f"{STATIC_DATA['base_url']}/{p_smileys[0]}"
            dir_json = json.loads(requests.get(f"{dir_url}?json=true").text)
            free_smiley_url = f"{dir_url}/{random.choice(dir_json['files'])['name']}"
            free_smiley_url = format_sirv_smiley_url(free_smiley_url, message.server.id)

            # Create the embed
            embed = discord.Embed(title=(title if do_title else ""))
            embed.set_image(url=free_smiley_url)
            await bot.send_message(message.channel, content=(f"<@{message.author.id}>" if do_mention else ""), embed=embed)

            return

        # Iterate old smiley types in file
        for record in STATIC_DATA["old_smileys"]:
            if emoji_name not in record["paid_smileys"]:
                continue

            print(message.content + " detected.")

            # Get parameters for embed
            title = random.choice(STATIC_DATA["titles"])
            free_smiley_url = random.choice(record["free_smileys"])

            # Create the embed
            embed = discord.Embed(title=(title if do_title else ""))
            embed.set_image(url=free_smiley_url)
            await bot.send_message(message.channel, content=(f"<@{message.author.id}>" if do_mention else ""), embed=embed)

            return


@bot.event
async def on_ready():
    await bot.change_presence(game=discord.Game(name=STATIC_DATA["game"]))
    print("Bot is ready.")
    print([s.name for s in bot.servers])


@bot.event
async def on_message(message: discord.Message):
    try:
        # Check if not myself
        if message.author == bot.user:
            return

        await correct_smiley([DISCORD_EMOJI_TO_CODE[e].replace(':', '') for e in emoji_lis(message.content)], message)

        await bot.process_commands(message)

    except Exception as e:
        bot.send_message(message.channel, ":x: **An error occurred.**")
        print(f"Error: {str(e)}")


@bot.command(pass_context=True, name="help", aliases=["h"])
async def command_help(ctx: commands.Context):
    print("help")
    # "help": "\n",
    await bot.say(f"{STATIC_DATA['help']}")


@bot.command(pass_context=True, name="smiley", aliases=["s"])
async def command_smiley(ctx: commands.Context, emoji_name_message: str):
    await correct_smiley([emoji_name_message], ctx.message, do_mention=False, do_title=False)


@bot.command(pass_context=True, name="size", aliases=["height"])
async def command_size(ctx: commands.Context, size: str):
    # Check for permissions
    if not ctx.message.author.server_permissions.manage_channels:
        await bot.say(":x: **This command requires you to have `Manage Channels` permission to use it.**")
        return

    # Validate size parameter
    try:
        size = int(size)
    except ValueError:
        await bot.say("Invalid size.")
        return

    if size < MIN_SMILEY_SIZE or size > MAX_SMILEY_SIZE:
        await bot.say(f"Size must be between {MIN_SMILEY_SIZE} and {MAX_SMILEY_SIZE}.")
        return

    # Lock thread
    async with DYNAMIC_DATA_LOCK:
        with open(DYNAMIC_DATA_FILENAME, 'w') as f:
            # Change size and save in file
            DYNAMIC_DATA["sizes"][ctx.message.server.id] = size
            json.dump(DYNAMIC_DATA, f, indent=4)

    print(f"Size changed to {size} in {ctx.message.server}.")
    await bot.say(f"Size changed to {size}.")


# Reload data every once in a while
async def reload_data_continuously():
    global STATIC_DATA, DISCORD_CODE_TO_EMOJI, DISCORD_EMOJI_TO_CODE
    while True:
        await asyncio.sleep(500)
        t0 = time.time()

        with open(STATIC_DATA_FILENAME, 'r') as f:
            STATIC_DATA = json.load(f)

        print(f"Reloaded data in {int(round((time.time() - t0) * 1000))} ms.")


bot.loop.create_task(reload_data_continuously())
bot.run(TOKEN)
