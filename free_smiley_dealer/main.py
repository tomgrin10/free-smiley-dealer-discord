import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

import discord
import environs
import nest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from cogs.dblapi import TopGG
from cogs.smileydealer import FreeSmileyDealerCog
from database import Database
from extensions import *

nest_asyncio.apply()

async def main():
    env = environs.Env()
    env.read_env()

    discord_log_handler = DiscordChannelLoggingHandler(env.int('LOG_CHANNEL'))
    # noinspection PyArgumentList
    logging.basicConfig(
        level=logging.INFO,
        handlers=(
            discord_log_handler,
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler("log.txt", maxBytes=100_000, backupCount=1)),
        datefmt="%d-%m-%Y %H:%M:%S",
        format="**{levelname}:** *{asctime}*\n{message}",
        style="{"
    )
    logger = logging.getLogger(__name__)

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
    discord_log_handler.bot = bot
    logger.info('Added discord logging handler.')

    try:
        await bot.add_cog(FreeSmileyDealerCog(bot, database))
        dbl_api_key = env.str('DBL_API_KEY', None)
        if dbl_api_key:
            logger.info('MONGODB_URI environment variable supplied, '
                        'setting up TopGG cog.')
            await bot.add_cog(TopGG(bot, dbl_api_key))
        else:
            logger.info('MONGODB_URI environment variable not supplied, '
                        'not setting up TopGG cog.')

        bot.run(env.str('DISCORD_TOKEN'))
    except Exception as e:
        logger.exception(e)


if __name__ == "__main__":
    asyncio.run(main())
