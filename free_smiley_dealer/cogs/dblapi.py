import asyncio
import logging

import dbl
from discord.ext import commands, tasks


class TopGG(commands.Cog):
    """Handles interactions with the top.gg API"""

    def __init__(self, bot, token):
        self.bot = bot
        self.token = token
        self.dbl_client = dbl.Client(self.bot, self.token)

    @tasks.loop(minutes=30.0)
    async def update_stats(self):
        """This function runs every 30 minutes to automatically update your server count"""
        logging.info('Attempting to post server count')
        try:
            await self.dbl_client.post_guild_count()
            logging.info('Posted server count ({})'.format(self.dbl_client.guild_count()))
        except Exception as e:
            logging.exception('Failed to post server count\n{}: {}'.format(type(e).__name__, e))
