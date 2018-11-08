from discord.ext import commands
import asyncio
import dbl
import logging


class DiscordBotsOrgAPI:
    """Handles interactions with the discordbots.org API"""

    def __init__(self, bot: commands.Bot, api_key: str):
        self.bot = bot
        self.token = api_key  # set this to your DBL token
        self.dblpy = dbl.Client(self.bot, self.token)
        self.bot.loop.create_task(self.update_stats())

    async def update_stats(self):
        await self.bot.wait_until_ready()
        """This function runs every 30 minutes to automatically update your server count"""

        while True:
            logging.info('attempting to post server count')
            try:
                await self.dblpy.post_server_count()
                logging.info(f'posted server count ({len(self.bot.guilds)})')
            except Exception as e:
                logging.error(f'Failed to post server count\n{type(e).__name__}: {e}')
            await asyncio.sleep(1800)
