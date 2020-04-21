from typing import Optional

import discord
from discord.ext import commands


__all__ = ["SettingsChannelConverter", "SettingsDefaultConverter"]


class SettingsDefaultConverter(commands.Converter):
    def __init__(self, default_value=None):
        self.default_value = default_value

    async def convert(self, ctx, arg):
        if "default".startswith(arg):
            return self.default_value
        else:
            raise commands.BadArgument("Not default.")


class SettingsChannelConverter(commands.TextChannelConverter):
    async def convert(self, ctx: commands.Context, arg: str) -> Optional[discord.TextChannel]:
        """
        :return: The target channel of the command
                 None - If no channel given, guild default
        """
        if "channel".startswith(arg):
            return ctx.channel
        if "server".startswith(arg) or "guild".startswith(arg):
            return None

        return await super().convert(ctx, arg)