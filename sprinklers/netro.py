import asyncio

import aiohttp

import errors
from . import SprinklerProvider, register

API = "https://api.netrohome.com/v1"


class NetroSprinkler(SprinklerProvider):
    name = "netro"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self.serial = config.get("serial") or config.get("device_id") or ""
        self.api_key = config.get("api_key") or config.get("password") or ""

    async def connect(self) -> bool:
        if not self.serial:
            errors.log_error("netro.connect", "No serial number provided")
            return False
        try:
            key = self.api_key or self.serial
            async with self._session.get(
                f"{API}/devices",
                headers={"Authorization": key},
            ) as r:
                if r.status != 200:
                    text = await r.text()
                    errors.log_error("netro.connect", f"API error {r.status}: {text[:200]}")
                    return False
                self._connected = True
                return True
        except Exception as e:
            errors.log_error("netro.connect", str(e), exc_info=True)
            return False

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self._connected:
            ok = await self.connect()
            if not ok:
                return False
        try:
            minutes = max(1, round(duration_seconds / 60))
            zone_id = int(zone_id)
            key = self.api_key or self.serial
            async with self._session.post(
                f"{API}/devices/{self.serial}/zones/{zone_id}/start",
                headers={"Authorization": key},
                json={"duration_minutes": minutes},
            ) as r:
                if r.status == 200 or r.status == 201:
                    return True
                text = await r.text()
                errors.log_error("netro.start_zone", f"API error {r.status}: {text[:200]}")
                return False
        except Exception as e:
            errors.log_error("netro.start_zone", str(e), exc_info=True)
            return False

    async def stop_zone(self) -> bool:
        if not self._connected:
            return False
        try:
            key = self.api_key or self.serial
            async with self._session.post(
                f"{API}/devices/{self.serial}/stop",
                headers={"Authorization": key},
            ) as r:
                return r.status == 200 or r.status == 201
        except Exception as e:
            errors.log_error("netro.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("netro", NetroSprinkler)
