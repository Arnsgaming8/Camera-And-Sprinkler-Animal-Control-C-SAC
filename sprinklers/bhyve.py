import asyncio
import json
from datetime import datetime, timezone

import aiohttp
import yaml

import errors
from state import get_config_path
from . import SprinklerProvider, register

API = "https://api.orbitbhyve.com/v1"
WS = "wss://api.orbitbhyve.com/v1/events"
PING_INTERVAL = 25


class BHyveSprinkler(SprinklerProvider):
    name = "bhyve"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self.token: str | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._ping_task: asyncio.Task | None = None
        self._token_for_ws: str | None = None
        self._connected = False

        email = config.get("email") or config.get("bhyve_email") or ""
        password = config.get("password") or config.get("bhyve_password") or ""
        self._email = email
        self._password = password

        device_id = config.get("device_id") or config.get("device_id") or ""
        if not device_id and "device_id" in config:
            device_id = config["device_id"]
        self.device_id = device_id

    async def connect(self) -> bool:
        try:
            payload = {"session": {"email": self._email, "password": self._password}}
            for attempt in range(3):
                try:
                    async with self._session.post(f"{API}/session", json=payload) as r:
                        text = await r.text()
                        if r.status >= 500:
                            if attempt < 2:
                                await asyncio.sleep(2 ** attempt)
                                continue
                            errors.log_error("bhyve.login", f"B-hyve login failed ({r.status}): {text[:200]}")
                            return False
                        if r.status >= 400:
                            errors.log_error("bhyve.login", f"B-hyve login failed ({r.status}): {text[:200]}")
                            return False
                        data = json.loads(text)
                        self.token = data["orbit_session_token"]
                        self._connected = True
                        return True
                except aiohttp.ClientError as e:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    errors.log_error("bhyve.login", f"B-hyve login network error: {e}")
                    return False
        except Exception as e:
            errors.log_error("bhyve.login", str(e), exc_info=True)
            return False

    async def _connect_ws(self):
        if self.ws and not self.ws.closed and self._token_for_ws == self.token:
            return
        if self.ws and not self.ws.closed:
            await self.ws.close()
        self.ws = None
        self.ws = await self._session.ws_connect(WS)
        self._token_for_ws = self.token
        await self.ws.send_json({"event": "app_connection", "orbit_session_token": self.token})

    async def _ping_loop(self):
        try:
            while self.ws and not self.ws.closed:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await self.ws.send_json({"event": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def start_zone(self, zone_id: str | int, duration_seconds: int) -> bool:
        if not self.token:
            ok = await self.connect()
            if not ok:
                return False
        try:
            await self._connect_ws()
            minutes = max(1, round(duration_seconds / 60))
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            zone = int(zone_id)
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [{"station": zone, "run_time": minutes}],
            }
            await self._send_ws_json(payload)
            started = False
            for _ in range(10):
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.json()
                        ev = data.get("event")
                        if ev == "change_mode" or ev == "watering_in_progress_notification":
                            started = True
                            break
                except asyncio.TimeoutError:
                    break
            if not started:
                errors.log_error("bhyve.start_zone", "No confirmation from server")
                return False
            if self._ping_task is None or self._ping_task.done():
                self._ping_task = asyncio.ensure_future(self._ping_loop())
            return True
        except Exception as e:
            errors.log_error("bhyve.start_zone", str(e), exc_info=True)
            return False

    async def _send_ws_json(self, payload):
        try:
            await self.ws.send_json(payload)
        except (aiohttp.ClientConnectionResetError, aiohttp.ClientError):
            self.ws = None
            self._token_for_ws = None
            await self._connect_ws()
            await self.ws.send_json(payload)

    async def stop_zone(self) -> bool:
        try:
            await self._connect_ws()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [],
            }
            await self._send_ws_json(payload)
            return True
        except Exception as e:
            errors.log_error("bhyve.stop_zone", str(e), exc_info=True)
            return False

    async def disconnect(self):
        self._connected = False
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None
        if self.ws and not self.ws.closed:
            await self.ws.close()
            self.ws = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    @property
    def connected(self) -> bool:
        return self._connected


register("bhyve", BHyveSprinkler)
