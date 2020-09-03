from enum import Enum
from typing import Optional, TypeVar, Type, Generic

import discord
from discord.ext import commands

Default = object()
All = object()


class SettingsDefaultConverter(commands.Converter):
    _DefaultValueType = TypeVar('_DefaultValueType')

    def __init__(self, default_value: _DefaultValueType = Default):
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


class SettingsAllConverter(commands.TextChannelConverter):
    async def convert(self, ctx: commands.Context, arg: str) -> All:
        if arg.lower() == 'all':
            return All
        else:
            raise commands.BadArgument("Not all.")


_EnumConverterType = TypeVar('_EnumConverterType', bound=Enum)


NoValue = object()


def create_enum_converter(enum_type: Type[_EnumConverterType]):
    class EnumConverter(commands.Converter):
        async def convert(self, ctx: commands.Context, arg: str) -> _EnumConverterType:
            for enum_obj in enum_type:
                enum_obj: Enum

                if enum_obj.name.lower().startswith(arg.lower()):
                    return enum_obj

            enum_type_name: str = enum_type.__name__.lower()
            raise commands.BadArgument(
                f"Invalid {enum_type_name}. {enum_type_name.capitalize()} options are " +
                ', '.join(f'`{enum_obj.name.lower()}`' for enum_obj in enum_type))

    return EnumConverter
