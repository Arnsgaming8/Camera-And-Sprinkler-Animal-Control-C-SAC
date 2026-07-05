import asyncio

import aiohttp

import errors
from . import SprinklerProvider, register


class OpenSprinklerSprinkler(SprinklerProvider):
    name = "opensprinkler"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._host = config.get("host") or ""
        self._password = config.get("password") or ""
        self._port = int(config.get("port", 80))

    async def connect(self) -> bool:
        if not self._host:
            errors.log_error("opensprinkler.connect", "No host provided")
            return False
        try:
            from pyopensprinkler import OpenSprinkler
            base = f"http://{self._host}:{self._port}"
            self._api = OpenSprinkler(base, self._password)
            await self._api.refresh()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("opensprinkler.connect", str(e), exc_info=True)
            return False

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self._connected or not self._api:
            return False
        try:
            minutes = max(1, round(duration_seconds / 60))
            zone_id = int(zone_id)
            await self._api.run_station(zone_id, minutes)
            return True
        except Exception as e:
            errors.log_error("opensprinkler.start_zone", str(e), exc_info=True)
            return False

    async def stop_zone(self) -> bool:
        try:
            if self._api:
                ok = await self._api.stop_all_stations()
                return bool(ok)
            return False
        except Exception as e:
            errors.log_error("opensprinkler.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("opensprinkler", OpenSprinklerSprinkler)
