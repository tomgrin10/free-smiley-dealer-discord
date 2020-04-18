import logging
from logging.handlers import RotatingFileHandler
import sys

import environs
import pymongo

from database import Database
from extensions import *
from cogs.smileydealer import FreeSmileyDealerCog
from cogs.dblapi import TopGG

if __name__ == "__main__":
    env = environs.Env()
    env.read_env()

    discord_log_handler = DiscordChannelLoggingHandler()
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
    pymongo_client = pymongo.MongoClient(
        env.str('MONGODB_URI', None),
        serverSelectionTimeoutMS=3)

    database = Database(pymongo_client)
    logger.info('Set up mongodb client successfully.')

    bot = BasicBot(database)
    discord_log_handler.bot = bot
    logger.info('Added discord logging handler.')

    try:
        bot.add_cog(FreeSmileyDealerCog(bot, database))
        dbl_api_key = env.str('DBL_API_KEY', None)
        if dbl_api_key:
            bot.add_cog(TopGG(bot, dbl_api_key))
            
        bot.run(env.str('DISCORD_TOKEN'))
    except Exception as e:
        logger.exception(e)
