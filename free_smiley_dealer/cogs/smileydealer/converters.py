from enum import Enum
from typing import Optional, TypeVar, Type

import discord
from discord.ext import commands

__all__ = ["SettingsChannelConverter", "SettingsDefaultConverter"]


class SettingsDefaultConverter(commands.Converter):
    _DefaultValueType = TypeVar('_DefaultValueType')

    def __init__(self, default_value: _DefaultValueType = None):
        self.default_value = default_value

    async def convert(self, ctx: commands.Context, arg: str) -> _DefaultValueType:
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


class EnumConverter(commands.Converter):
    _EnumType = TypeVar('_EnumType', bound=Enum)

    def __init__(self, enum_type: Type[_EnumType]):
        self.enum_type = enum_type

    async def convert(self, ctx: commands.Context, arg: str) -> _EnumType:
        for enum_obj in self.enum_type:
            enum_obj: Enum

            if enum_obj.name.lower().startswith(arg.lower()):
                return enum_obj
