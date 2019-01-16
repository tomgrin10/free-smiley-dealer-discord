import sys

from extensions import *
from cogs.smileydealer import FreeSmileyDealerCog
from cogs.dblapi import DiscordBotsOrgAPI

if __name__ == "__main__":
    bot = BasicBot()

    logging.basicConfig(
        level=logging.INFO,
        handlers=(LoggingHandler(bot), logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILENAME,)),
        datefmt="%d-%m-%Y %H:%M:%S",
        format="**{levelname}:** *{asctime}*\n{message}", style="{")

    try:
        bot.add_cog(FreeSmileyDealerCog(bot))
        bot.add_cog(DiscordBotsOrgAPI(bot, bot.config["dbl_api_key"]))
        bot.run()
    except Exception as e:
        logging.exception(e)
