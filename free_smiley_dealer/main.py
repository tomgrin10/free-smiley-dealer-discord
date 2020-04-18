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

    pymongo_client = pymongo.MongoClient(env.str('MONGODB_URI', None))
    database = Database(pymongo_client)

    bot = BasicBot(database)

    # noinspection PyArgumentList
    logging.basicConfig(
        level=logging.INFO,
        handlers=(
            DiscordChannelLoggingHandler(bot),
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler("log.txt", maxBytes=100_000, backupCount=1)),
        datefmt="%d-%m-%Y %H:%M:%S",
        format="**{levelname}:** *{asctime}*\n{message}",
        style="{"
    )

    try:
        bot.add_cog(FreeSmileyDealerCog(bot, database))
        dbl_api_key = env.str('DBL_API_KEY', None)
        if dbl_api_key:
            bot.add_cog(TopGG(bot, dbl_api_key))
            
        bot.run(env.str('DISCORD_TOKEN'))
    except Exception as e:
        logging.exception(e)
