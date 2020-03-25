import os
from dataclasses import dataclass
from typing import Optional, Final

import environs


class ConfigError(Exception):
    pass


@dataclass
class Config:
    discord_token: str
    dbl_api_key: Optional[str]

    def __init__(self):
        self.load()

    def load(self):
        env = environs.Env()
        env.read_env()

        self.discord_token = env.str('DISCORD_TOKEN')
        if not self.discord_token:
            raise ConfigError("DISCORD_TOKEN environment variable not set.")

        self.dbl_api_key = env.str('DBL_API_KEY')
