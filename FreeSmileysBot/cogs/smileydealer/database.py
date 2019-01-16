from collections import OrderedDict
from typing import *

import pymongo
from discord.ext import commands


def is_enabled():
    def predicate(ctx: commands.Context):
        return ctx.cog.db.Setting("enabled", ctx.guild.id, ctx.channel.id).read() is not False

    return commands.check(predicate)


def author_not_muted():
    def predicate(ctx: commands.Context):
        return ctx.author.id not in ctx.cog.db.Setting("muted_users", ctx.guild.id, ctx.channel.id)

    return commands.check(predicate)


class Database:
    """
    Class representing a mongodb database
    """

    def __init__(self, static_data):
        self._static_data = static_data

        self._client = pymongo.MongoClient(serverSelectionTimeoutMS=3)
        self._client.server_info()
        self._db = self._client["smiley_dealer"]
        self._cache = OrderedDict()
        self.data_fixer_upper()

    def Setting(self, setting_name: str, guild_id: int = None, channel_id: Optional[int] = None):
        return _Setting(self, setting_name, guild_id, channel_id)

    def _verify_cache_integrity(self):
        while len(self._cache) > 20:
            self._cache.popitem()

    def _get_guild_document(self, guild_id, *, cache=True) -> Optional[Dict]:
        # Get document from cache
        if cache:
            doc = self._cache.get(guild_id)
            if doc:
                self._cache.move_to_end(guild_id, last=False)
                return doc

        # Get document from database
        doc = self._db["guilds"].find_one({"_id": str(guild_id)})
        self._cache[guild_id] = doc
        self._verify_cache_integrity()
        return doc

    def data_fixer_upper(self):
        """
        Update the data structure.
        """
        pass

    def get_global_default_setting(self, setting_name: str):
        return self._static_data["default_settings"][setting_name]

    def _get_setting_from_document(self, setting_name, document, channel_id: Optional[int] = None):
        if not document:
            return self.get_global_default_setting(setting_name)

        # Try to get channel setting
        if channel_id:
            try:
                return document["settings"][str(channel_id)][setting_name]
            except KeyError:
                pass

        # Try to get default server setting
        try:
            return document["settings"]['default'][setting_name]
        except KeyError:
            pass

        return

    def _get_settings_dict(self, guild_id: Optional[int] = None, channel_id: Optional[int] = None):
        """
        Gets the settings of the channel, considers default server and global
        :param guild_id: None - If wants to get the global default settings
        :param channel_id: None - If wants to get the guild default settings
        :return: The settings dictionary
        """
        if not guild_id:
            return self._static_data["default_settings"]

        guild_data = self._get_guild_document(guild_id)
        if not guild_data:
            return self._static_data["default_settings"]

        settings = dict()
        for setting_name in self._static_data["default_settings"]:
            settings[setting_name] = self._get_setting_from_document(setting_name, guild_data, channel_id)

    def _get_setting(self, setting_name: str, guild_id: Optional[int] = None, channel_id: Optional[int] = None) -> Any:
        """
        Gets channel-specific/guild-specific or global default setting by name
        :param setting_name: Name of the setting
        :param guild_id: None - If wants to get the global default setting
        :param channel_id: None - If wants to get the guild default setting
        :return: The setting value
        """
        if not guild_id:
            return self.get_global_default_setting(setting_name)

        guild_data = self._get_guild_document(guild_id)
        value = self._get_setting_from_document(setting_name, guild_data, channel_id)

        if value is None:
            return self.get_global_default_setting(setting_name)

        return value

    def _delete_setting(self, setting_name: str, guild_id: int, channel_id: Optional[int] = None):
        """
        Deletes the specified setting from the database
        :param setting_name: Name of the setting
        :param guild_id
        :param channel_id: None - If wants to delete the guild default setting
        """
        self._db["guilds"].update_one(
            {"_id": str(guild_id)},
            {"$unset":
                {f"settings.{str(channel_id) if channel_id else 'default'}.{setting_name}": ""}})

    def _change_setting(self, setting_name: str, setting_value: Any = None, *, guild_id: int, channel_id: Optional[int] = None,
                        operation="set", upsert=True):
        """
        Changes the specified setting to the given value
        :param setting_name: Name of the setting
        :param setting_value: The new value of the setting
                              None - If wants to delete the setting
        :param guild_id
        :param channel_id: None - If wants to change the guild default setting
        :param operation:
        :param upsert:
        :return:
        """
        if setting_value is None:
            self._delete_setting(setting_name, guild_id, channel_id)
        else:
            # Change the value of the setting
            self._db["guilds"].update_one(
                {"_id": str(guild_id)},
                {f"${operation}":
                    {f"settings.{str(channel_id) if channel_id else 'default'}.{setting_name}": setting_value}},
                upsert=upsert)

        # Remove from cache
        if guild_id in self._cache:
            self._cache.pop(guild_id)


class _Setting:
    def __init__(self, db: Database, setting_name: str, guild_id: int = None, channel_id: Optional[int] = None):
        self.db = db
        self.setting_name = setting_name
        self.guild_id = guild_id
        self.channel_id = channel_id

    def read(self) -> Any:
        return self.db._get_setting(self.setting_name, self.guild_id, self.channel_id)

    def change(self, new_value: Any):
        if not self.guild_id:
            raise ValueError("Guild id is not supplied.")

        return self.db._change_setting(self.setting_name, new_value, guild_id=self.guild_id, channel_id=self.channel_id)

    def delete(self):
        if not self.guild_id:
            raise ValueError("Guild id is not supplied.")

        return self.db._delete_setting(self.setting_name, guild_id=self.guild_id, channel_id=self.channel_id)

    def push(self, value: Any):
        if not self.guild_id:
            raise ValueError("Guild id is not supplied.")

        return self.db._change_setting(self.setting_name, value, guild_id=self.guild_id, channel_id=self.channel_id, operation="push")

    def pop(self, value: Any):
        if not self.guild_id:
            raise ValueError("Guild id is not supplied.")

        return self.db._change_setting(self.setting_name, value, guild_id=self.guild_id, channel_id=self.channel_id, operation="pull", upsert=False)

    def __contains__(self, value: Any) -> bool:
        data = self.read()
        return data and value in data
