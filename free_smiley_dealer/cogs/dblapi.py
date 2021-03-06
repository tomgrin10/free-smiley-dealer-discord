import asyncio
import logging

import dbl
from discord.ext import commands, tasks
from discord.ext.commands import Bot

logger = logging.getLogger(__name__)


class TopGG(commands.Cog):
    """Handles interactions with the top.gg API"""

    def __init__(self, bot: Bot, token: str):
        self.bot = bot
        self.token = token
        self.dbl_client = dbl.Client(self.bot, self.token)

    @tasks.loop(minutes=30.0)
    async def update_stats(self):
        """This function runs every 30 minutes to automatically update your server count"""
        logger.info('Attempting to post server count')
        try:
            await self.dbl_client.post_guild_count()
            logger.info('Posted server count ({})'.format(self.dbl_client.guild_count()))
        except Exception as e:
            logger.exception('Failed to post server count\n{}: {}'.format(type(e).__name__, e))
