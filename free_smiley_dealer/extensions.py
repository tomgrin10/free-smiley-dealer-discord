import asyncio
import logging
import time
import datetime
from typing import *

import discord
from discord.ext import commands

from database import Database

# Constants
MESSAGE_CHARACTER_LIMIT = 2000
T0 = time.time()

__all__ = ['Command', 'command', 'BasicBot', 'DiscordChannelLoggingHandler', 'CommandConverter']


def split_message_for_discord(content: str, divider: str = None) -> Iterable[str]:
    if divider is None:
        segments = content
    else:
        segments = [s + divider for s in content.split(divider)]

    message = ""
    for segment in segments:
        if len(message) + len(segment) >= MESSAGE_CHARACTER_LIMIT:
            yield message
            message = ""
        else:
            message += segment

    yield message


class Command(commands.Command):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.examples = kwargs.pop("examples", ())
        self.category = kwargs.pop("category", None)
        self.emoji = kwargs.pop("emoji", None)
        self.opposite = kwargs.pop("opposite", None)

        func_cooldown = kwargs.pop("func_cooldown", None)
        if func_cooldown:
            self._buckets = CooldownMapping(*func_cooldown)


def command(**kwargs):
    return commands.command(cls=Command, **kwargs)


class BasicBot(commands.Bot):
    def __init__(self):
        self.db = Database()

        super().__init__(
            command_prefix=commands.when_mentioned_or(self.db.config["prefix"])
        )

        self.add_cog(BasicBot.Commands(self))

    async def setup_activities(self):
        await self.wait_until_ready()

        if "activities" in self.db.config:
            self.loop.create_task(self.continuously_change_presence())

    def run(self):
        super().run(self.db.config["token"])

    async def on_ready(self):
        await self.setup_activities()
        logging.info("Bot is ready.")
        logging.info(f"{len(self.guilds)} guilds:\n{[g.name for g in sorted(self.guilds, key=lambda g: g.member_count, reverse=True)[:50]]}")

    async def on_error(self, event_method, *args, **kwargs):
        logging.exception("")

    async def log(self, content: str, channel: discord.TextChannel = None):
        if not channel:
            channel = self.get_channel(int(self.db.config["log_channel_id"]))
        content = content.replace("@everyone", "`@everyone`").replace("@here", "`@here`")

        for segment in split_message_for_discord(content):
            await channel.send(segment)

    async def ask_question(self, message: discord.Message, user: discord.User,
                           emojis: Sequence[Union[discord.Emoji, str]] = ('✅', '❌'), *, timeout: int = 60) -> discord.Emoji:
        def check(r: discord.Reaction, u: discord.User):
            return u == user and (r.emoji in emojis or str(r.emoji) in emojis)

        for e in emojis:
            await message.add_reaction(e)

        reaction = (await self.wait_for("reaction_add", timeout=timeout, check=check))[0]
        return reaction.emoji

    async def continuously_change_presence(self):
        await self.wait_until_ready()

        def make_activity(activity_str: str) -> discord.Activity:
            # If is string
            first_word = activity_str.split(' ')[0]
            try:
                act_type = getattr(discord.ActivityType, first_word.lower())
            except AttributeError:
                raise discord.ClientException(f"Activity `{activity_str}` error.")

            act_name = activity_str.replace(f"{first_word} ", "")

            return discord.Activity(
                type=act_type,
                name=act_name.format(guilds_count=len(self.guilds), prefix=self.db.config["prefix"]))

        while True:
            for activity_str in self.db.config["activities"]:
                await self.change_presence(activity=make_activity(activity_str))
                await asyncio.sleep(60)

    class Commands:
        def __init__(self, bot):
            self.bot = bot

        @command(name="invite", aliases=["inv"], category="commands",
                 brief="Invite me to your server!")
        async def command_invite(self, ctx):
            try:
                await ctx.send(self.bot.db.config["invite_url"])
            except KeyError:
                pass

        @command(name="server", aliases=[], category="commands",
                 brief="Get an invite to my support server for help or suggestions.")
        async def command_server(self, ctx):
            try:
                await ctx.send(self.bot.db.config["support_guild_url"])
            except KeyError:
                pass

        @command(name="donate", aliases=["support"], category="commands",
                 brief="Get a donation link to help me maintain this bot.")
        async def command_donate(self, ctx):
            try:
                await ctx.send(self.bot.db.config["donate_url"])
            except KeyError:
                pass

        @command(name="uptime", hidden=True)
        async def command_uptime(self, ctx):
            delta = datetime.timedelta(seconds=time.time() - T0)
            days = delta.days
            hours, rem = divmod(delta.seconds, 3600)
            mins, secs = divmod(rem, 60)
            await ctx.send(f"{days}d {hours}h {mins}m {secs}s")

        @command(name="log", hidden=True)
        @commands.is_owner()
        async def command_log(self, ctx: commands.Context, *, to_log):

            shortcuts = {
                "len": "len(self.bot.guilds)",
                "names": "[g.name for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)[:50]]",
            }

            if to_log in shortcuts:
                to_log = shortcuts[to_log]

            logging.info(f"`{ctx.message.content}`\n{eval(to_log)}")


class DiscordChannelLoggingHandler(logging.Handler):
    def __init__(self, bot: BasicBot, min_level=logging.INFO):
        super().__init__()
        self.bot = bot
        self.min_level = min_level

    def emit(self, record: logging.LogRecord):
        if record.levelno < self.min_level:
            return

        formatted_record = self.format(record)
        if self.bot.is_ready():
            self.bot.loop.create_task(self.bot.log(formatted_record))


class CommandConverter(commands.Converter):
    def __init__(self, *, search_aliases=True):
        self.search_aliases = search_aliases

    async def convert(self, ctx: commands.Context, arg: str) -> commands.Command:
        for command in ctx.bot.commands:
            if command.name == arg or (self.search_aliases and arg in command.aliases):
                return command

        raise commands.BadArgument(f"`{arg}` is not a commands name or alias.")


class CooldownMapping(commands.CooldownMapping):
    def __init__(self, factory, bucket_type: Sequence[commands.BucketType]):
        super().__init__(factory)
        self._bucket_type = (bucket_type,) if not isinstance(bucket_type, commands.BucketType) else bucket_type

    def _bucket_key(self, msg):
        def get_key(bucket_type):
            if bucket_type is commands.BucketType.default:
                return 0
            elif bucket_type is commands.BucketType.user:
                return msg.author.id
            elif bucket_type is commands.BucketType.guild:
                return (msg.guild or msg.author).id
            elif bucket_type is commands.BucketType.channel:
                return msg.channel.id
            elif bucket_type is commands.BucketType.category:
                return (msg.channel.category or msg.channel).id

        return frozenset(get_key(bucket_type) for bucket_type in self._bucket_type)

    def _verify_cache_integrity(self):
        # we want to delete all cache objects that haven't been used
        # in a cooldown window. e.g. if we have a  command that has a
        # cooldown of 60s and it has not been used in 60s then that key should be deleted
        current = time.time()
        dead_keys = [k for k, v in self._cache.items() if current > v._last + v.per]
        for k in dead_keys:
            del self._cache[k]

    def get_bucket(self, message):
        self._verify_cache_integrity()
        key = self._bucket_key(message)
        if key not in self._cache:
            if isinstance(self._cooldown, commands.Cooldown):
                bucket = self._cooldown.copy()
            # elif asyncio.iscoroutinefunction(self._cooldown):
            #    bucket = await self._cooldown(message)
            elif callable(self._cooldown):
                bucket = self._cooldown(message)
            else:
                raise TypeError("Cooldown factory should be a Cooldown object/function/coroutine.")

            self._cache[key] = bucket
        else:
            bucket = self._cache[key]

        return bucket
