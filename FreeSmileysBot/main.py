import discord
from discord.ext import commands
import asyncio
import json
import random
import time

# Constants
TOKEN_FILENAME = "token.json"
DATA_FILENAME = "data.json"
DISCORD_EMOJI_CODES_FILENAME = "discord_emoji_codes.json"

# Load data
with open(TOKEN_FILENAME) as f:
    TOKEN = json.load(f)["token"]
with open(DATA_FILENAME, 'r') as f:
    DATA = json.load(f)
with open(DISCORD_EMOJI_CODES_FILENAME, 'r') as f:
    DISCORD_CODE_TO_EMOJI = json.load(f)
    DISCORD_EMOJI_TO_CODE = {v: k for k, v in DISCORD_CODE_TO_EMOJI.items()}

# Connect to discord
client: discord.Client = discord.Client()
bot: commands.Bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(DATA["prefix"])
)
bot.remove_command("help")


@bot.event
async def on_ready():
    await bot.change_presence(game=discord.Game(name=DATA["game"]))
    print("Bot is ready.")
    print([s.name for s in bot.servers])


@bot.event
async def on_message(message: discord.Message):
    # Check if not myself
    if message.author == bot.user:
        return

    # List all emojis in message
    def emoji_lis(s: str) -> list:
        for c in s:
            if c in DISCORD_EMOJI_TO_CODE:
                yield c

    # Iterate emojis in message
    for emoji_message in emoji_lis(message.content):
        # Iterate smiley types in file
        for record in DATA["smileys"]:
            if DISCORD_EMOJI_TO_CODE[emoji_message].replace(':', '') not in record["paid_smileys"]:
                continue

            print(message.content + " detected.")

            # Create the embed
            title = random.choice(DATA["titles"])
            free_smiley_url = random.choice(record["free_smileys"])
            embed = discord.Embed(title=title)
            embed.set_image(url=free_smiley_url)
            await bot.send_message(message.channel, content=f"<@{message.author.id}>", embed=embed)

            return

    await bot.process_commands(message)


@bot.command(pass_context=True, name="help", aliases=["h"])
async def command_help(ctx: commands.Context):
    print("help")
    # "help": "\n",
    await bot.say(f"""
<@{ctx.message.author.id}>
If you use regular (paid) smileys in your message, I will correct you.
Try it out, type `:joy:`.
You can also use the command `s!s` with the paid smiley name, example `s!s joy`.
Support server here: https://discord.gg/2XCVVx
    """)


@bot.command(pass_context=True, name="smiley", aliases=["s"])
async def command_smiley(ctx: commands.Context, emoji_name_message: str):
    # Iterate smiley types in file
    for record in DATA["smileys"]:
        if emoji_name_message not in record["paid_smileys"]:
            continue

        print(ctx.message.content + " detected.")

        # Create the embed
        free_smiley_url = random.choice(record["free_smileys"])
        embed = discord.Embed()
        embed.set_image(url=free_smiley_url)
        await bot.send_message(ctx.message.channel, content=f"<@{ctx.message.author.id}>", embed=embed)

        return



# Reload data every once in a while
async def reload_data_continuously():
    global DATA, DISCORD_CODE_TO_EMOJI, DISCORD_EMOJI_TO_CODE
    while True:
        await asyncio.sleep(500)
        t0 = time.time()

        with open(DATA_FILENAME, 'r') as f:
            DATA = json.load(f)

        print(f"Reloaded data in {int(round((time.time() - t0) * 1000))} ms.")


bot.loop.create_task(reload_data_continuously())
bot.run(TOKEN)
