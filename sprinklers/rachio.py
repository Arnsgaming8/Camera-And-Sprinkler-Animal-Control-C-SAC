import asyncio

import aiohttp

import errors
from . import SprinklerProvider, register

API = "https://api.rach.io/v1/public"


class RachioSprinkler(SprinklerProvider):
    name = "rachio"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self.token = config.get("api_token") or config.get("password") or ""
        self.person_id = None
        self.devices: list[dict] = []

    async def connect(self) -> bool:
        if not self.token:
            errors.log_error("rachio.connect", "No API token provided")
            return False
        try:
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            async with self._session.get(f"{API}/person/info", headers=headers) as r:
                if r.status != 200:
                    text = await r.text()
                    errors.log_error("rachio.connect", f"API error {r.status}: {text[:200]}")
                    return False
                data = await r.json()
                self.person_id = data.get("id")
                self.devices = data.get("devices", [])
                self._connected = True
                return True
        except Exception as e:
            errors.log_error("rachio.connect", str(e), exc_info=True)
            return False

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self._connected:
            ok = await self.connect()
            if not ok:
                return False
        try:
            zone_id = int(zone_id)
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            payload = {
                "id": zone_id,
                "duration": duration_seconds,
            }
            async with self._session.put(f"{API}/zone/start", json=payload, headers=headers) as r:
                if r.status == 204 or r.status == 200:
                    return True
                text = await r.text()
                errors.log_error("rachio.start_zone", f"API error {r.status}: {text[:200]}")
                return False
        except Exception as e:
            errors.log_error("rachio.start_zone", str(e), exc_info=True)
            return False

    async def stop_zone(self) -> bool:
        if not self._connected:
            return False
        try:
            headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
            for dev in self.devices:
                dev_id = dev.get("id")
                if dev_id:
                    async with self._session.put(f"{API}/device/{dev_id}/stop", headers=headers) as r:
                        pass
            return True
        except Exception as e:
            errors.log_error("rachio.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("rachio", RachioSprinkler)
