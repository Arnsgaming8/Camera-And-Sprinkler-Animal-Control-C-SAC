import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class ReolinkCameraProvider(CameraProvider):
    name = "reolink"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_motion_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from reolink import Reolink as ReolinkAPI
            self._api = ReolinkAPI(self._host, self._port, self._username, self._password)
            await self._api.get_host_data()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("reolink.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            motion = await self._api.get_motion_state()
            if motion:
                name = f"reolink_{self._host}"
                ev = CameraEvent(camera_name=name, timestamp=time.time())
                events.append(ev)
        except Exception as e:
            errors.log_error("reolink.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        if self._api:
            try:
                await self._api.logout()
            except Exception:
                pass
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("reolink", ReolinkCameraProvider)
