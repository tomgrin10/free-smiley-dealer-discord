import discord
from discord.ext import commands
import asyncio
import json
import emoji
import random

with open("config.json") as f:
    config = json.load(f)

client: discord.Client = discord.Client()
bot: commands.Bot = commands.Bot(command_prefix=config["prefix"])

with open(config["data_filename"], 'r') as f:
    smileys_data = json.load(f)


@bot.event
async def on_ready():
    await bot.change_presence(game=discord.Game(name=config["game"]))
    print("Bot is ready.")
    print(smileys_data)
    print([s.name for s in bot.servers])


@bot.event
async def on_message(message: discord.Message):
    # Iterate every record
    for record in smileys_data["smileys"]:
        # Iterate every paid smiley
        for p_smiley in record["paid_smileys"]:
            # Search for paid smiley in message
            if emoji.emojize(p_smiley, use_aliases=True) in message.content:
                print(message.content + " detected.")
                # Create the embed
                title = random.choice(smileys_data["titles"])
                embed = discord.Embed(title=title, description="<@{}>".format(message.author.id))
                free_smiley_url = random.choice(record["free_smileys"])
                embed.set_image(url=free_smiley_url)
                await bot.send_message(message.channel, embed=embed)

                return


bot.run(config["token"])
