import asyncio
import json
import logging
from typing import *

import discord
from discord.ext import commands

# Constants
CONFIG_FILENAME = "config.json"
LOG_FILENAME = "log.txt"
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
            content = content.replace("@everyone", "`@everyone`").replace("@here", "`@here`")
            for segment in split_message_for_discord(content):
                await channel.send(segment)

        channel = channel if channel else self.get_channel(self.config["logs_channel"])
        asyncio.create_task(async_log(content, channel))

    async def ask_question(self, message: discord.Message, user: discord.User, reactions=('✅', '❌'), timeout: int = 60) -> discord.Reaction:
        check = lambda r, u: u == user and str(r.emoji) in reactions

        for r in reactions:
            await message.add_reaction(r)

        reaction = (await self.wait_for("reaction_add", timeout=timeout, check=check))[0]
        return reaction


class LoggingHandler(logging.Handler):
    def __init__(self, bot: BasicBot):
        super().__init__()
        self.bot = bot

    def emit(self, record: logging.LogRecord):
        formatted_record = self.format(record)
        if self.bot.is_ready():
            self.bot.log(formatted_record)


T = TypeVar('T')


class Unordered(commands.Converter, Generic[T]):
    def convert(self, ctx: commands.Context, argument) -> T:
        for arg in ctx.args:
            try:
                return T(arg)
            except BadSimilarArgument as e:
                raise e
        raise UnorderedArgumentNotFound()


class UnorderedArgumentNotFound(commands.UserInputError):
    """
    Exception raised when an unordered argument is not found.
    """
    pass


class BadSimilarArgument(commands.BadArgument):
    """
    Exception raised when wrong argument seems like it might be a mistake.
    """
    pass
