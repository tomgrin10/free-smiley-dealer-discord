from typing import List, Dict, Any, Optional, Sequence


class StaticData:
    titles: Sequence[str]
    default_settings: Dict[str, Any]
    smileys: Sequence[Sequence[str]]

    def __init__(self, ):
        self._discord_token: str = None
        self._dbl_api_key: Optional[str] = None
        self.load()

    def load(self):
        self._discord_token = os.environ.get('DISCORD_TOKEN')
        if not self._discord_token:
            raise ConfigError("DISCORD_TOKEN environment variable not set.")

        self._dbl_api_key = os.environ.get('DBL_API_KEY')

    @property
    def discord_token(self):
        return self._discord_token

    @property
    def dbl_api_key(self):
        return self._dbl_api_key