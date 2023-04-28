import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

import discord
import environs
import nest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from cogs.smileydealer import FreeSmileyDealerCog
from database import Database
from extensions import *

nest_asyncio.apply()


async def main():
    env = environs.Env()
    env.read_env()

    logging_handlers = [
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler("log.txt", maxBytes=100_000, backupCount=1)
    ]
    if log_channel := env.int('LOG_CHANNEL', None):
        discord_log_handler = DiscordChannelLoggingHandler(log_channel)
        logging_handlers.append(discord_log_handler)

    # noinspection PyArgumentList
    logging.basicConfig(
        level=logging.INFO,
        handlers=logging_handlers,
        datefmt="%d-%m-%Y %H:%M:%S",
        format="**{levelname}:** *{asctime}*\n{message}",
        style="{"
    )
    logger = logging.getLogger(__name__)

    if log_channel:
        logger.info(f"Discord logging channel is set up.")
    else:
        logger.info(f"Discord logging channel is not set up.")

    logger.info('Setting up mongodb client.')
    mongodb_uri = env.str('MONGODB_URI', None)
    if not mongodb_uri:
        logger.info('MONGODB_URI environment variable not supplied, '
                    'connecting to localhost.')
    mongodb_client = AsyncIOMotorClient(
        mongodb_uri,
        serverSelectionTimeoutMS=1000
    )

    mongodb_database = mongodb_client[env('MONGODB_DB_NAME')]
    database = Database(mongodb_database)
    logger.info('Set up mongodb client successfully.')

    intents = discord.Intents.default()
    intents.message_content = True

    bot = BasicBot(intents, database)
    if log_channel:
        discord_log_handler.bot = bot
    logger.info('Added discord logging handler.')

    try:
        await bot.add_cog(FreeSmileyDealerCog(bot, database))

        bot.run(env.str('DISCORD_TOKEN'))
    except Exception as e:
        logger.exception(e)


if __name__ == "__main__":
    asyncio.run(main())
