import asyncio

import aiohttp

import errors
from . import SprinklerProvider, register


class RainBirdSprinkler(SprinklerProvider):
    name = "rainbird"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._host = config.get("host") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        if not self._host:
            errors.log_error("rainbird.connect", "No host provided")
            return False
        try:
            from pyrainbird import RainbirdController
            self._api = RainbirdController(self._host, self._password)
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("rainbird.connect", str(e), exc_info=True)
            return False

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self._connected or not self._api:
            return False
        try:
            minutes = max(1, round(duration_seconds / 60))
            zone_id = int(zone_id)
            ok = await self._api.irrigate_zone(zone_id, minutes)
            return bool(ok)
        except Exception as e:
            errors.log_error("rainbird.start_zone", str(e), exc_info=True)
            return False

    async def stop_zone(self) -> bool:
        try:
            if self._api:
                ok = await self._api.stop_irrigation()
                return bool(ok)
            return False
        except Exception as e:
            errors.log_error("rainbird.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("rainbird", RainBirdSprinkler)
