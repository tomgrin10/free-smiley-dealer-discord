import random

import discord


def iter_unique_values(iterable):
    seen = set()
    for item in iterable:
        if item not in seen:
            seen.add(item)
            yield item


def chance(chance_percent: float):
    return random.random() * 100 <= chance_percent


def user_full_name(user: discord.User):
    return f"{user.display_name}#{user.discriminator}"
