import asyncio

import aiohttp

import errors
from . import SprinklerProvider, register

API = "https://api.hydrawise.com/api/v1"


class HydrawiseSprinkler(SprinklerProvider):
    name = "hydrawise"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self.api_key = config.get("api_key") or config.get("password") or ""
        self.customer_id = None
        self.relays: list[dict] = []

    async def connect(self) -> bool:
        if not self.api_key:
            errors.log_error("hydrawise.connect", "No API key provided")
            return False
        try:
            async with self._session.get(
                f"{API}/customerdetails.php",
                params={"api_key": self.api_key},
            ) as r:
                if r.status != 200:
                    text = await r.text()
                    errors.log_error("hydrawise.connect", f"API error {r.status}: {text[:200]}")
                    return False
                data = await r.json()
                self.customer_id = data.get("customer_id")
                self.relays = data.get("relays", [])
                self._connected = True
                return True
        except Exception as e:
            errors.log_error("hydrawise.connect", str(e), exc_info=True)
            return False

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self._connected:
            ok = await self.connect()
            if not ok:
                return False
        try:
            minutes = max(1, round(duration_seconds / 60))
            zone_id = int(zone_id)
            for relay in self.relays:
                if relay.get("relay") == zone_id:
                    relay_name = relay.get("name", str(zone_id))
                    break
            async with self._session.get(
                f"{API}/suspendzone.php",
                params={"api_key": self.api_key, "relay_id": zone_id, "action": "run", "minutes": minutes},
            ) as r:
                if r.status == 200:
                    return True
                return False
        except Exception as e:
            errors.log_error("hydrawise.start_zone", str(e), exc_info=True)
            return False

    async def stop_zone(self) -> bool:
        try:
            for relay in self.relays:
                relay_id = relay.get("relay")
                if relay_id:
                    async with self._session.get(
                        f"{API}/suspendzone.php",
                        params={"api_key": self.api_key, "relay_id": relay_id, "action": "stop"},
                    ) as r:
                        pass
            return True
        except Exception as e:
            errors.log_error("hydrawise.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("hydrawise", HydrawiseSprinkler)
