import asyncio
import logging
import json
from typing import *

import discord
from discord.ext import commands

from cogs.dblapi import DiscordBotsOrgAPI
import cogs.smileydealer as smileydealer

# Constants
CONFIG_FILENAME = "config.json"
MESSAGE_CHARACTER_LIMIT = 2000


def split_message_for_discord(content: str, divider: str = None) -> Iterable[str]:
    if divider is None:
        segments = content
    else:
        segments = [s + divider for s in content.split(divider)]

    message = ""
    for segment in segments:
        if len(message) + len(segment) >= MESSAGE_CHARACTER_LIMIT:
            yield message
            message = ""
        else:
            message += segment

    yield message


class BasicBot(commands.Bot):
    def __init__(self):
        with open(CONFIG_FILENAME) as f:
            self.config = json.load(f)

        super().__init__(
            command_prefix=commands.when_mentioned_or(self.config["prefix"])
        )

    def run(self):
        super().run(self.config["token"])

    def log(self, content: str, channel: discord.TextChannel = None):
        async def async_log(content: str, channel: discord.TextChannel):
            print(content)
            for segment in split_message_for_discord(content):
                await channel.send(segment)

        channel = channel if channel else self.get_channel(self.config["logs_channel"])
        asyncio.create_task(async_log(content, channel))


if __name__ == "__main__":
    bot = BasicBot()
    logging.basicConfig(level=logging.INFO, handlers=(smileydealer.LoggingHandler(bot),))
    bot.add_cog(smileydealer.FreeSmileyDealerCog(bot))
    bot.add_cog(DiscordBotsOrgAPI(bot, bot.config["dbl_api_key"]))
    bot.run()
