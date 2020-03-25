import logging
from logging.handlers import RotatingFileHandler
import sys

from extensions import *
from cogs.smileydealer import FreeSmileyDealerCog
from cogs.dblapi import DiscordBotsOrgAPI

if __name__ == "__main__":
    bot = BasicBot()

    logging.basicConfig(
        level=logging.INFO,
        handlers=(
            DiscordChannelLoggingHandler(bot),
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler("log.txt", maxBytes=100_000, backupCount=1)),
        datefmt="%d-%m-%Y %H:%M:%S",
        format="**{levelname}:** *{asctime}*\n{message}", style="{")

    try:
        bot.add_cog(FreeSmileyDealerCog(bot))
        bot.add_cog(DiscordBotsOrgAPI(bot, bot.db.config["dbl_api_key"]))
            bot.add_cog(TopGG(bot, config.dbl_api_key))
    except Exception as e:
        logging.exception(e)
