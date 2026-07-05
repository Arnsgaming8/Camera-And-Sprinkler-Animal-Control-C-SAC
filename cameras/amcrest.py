import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class AmcrestCameraProvider(CameraProvider):
    name = "amcrest"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_event_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""
        self._channel = int(config.get("channel", 0))

    async def connect(self) -> bool:
        try:
            from amcrest import AmcrestCamera
            self._api = AmcrestCamera(self._host, self._port, self._username, self._password).camera
            info = self._api.software_information
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("amcrest.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            has_motion = self._api.is_motion_detected(self._channel)
            if has_motion:
                name = f"amcrest_{self._host}_ch{self._channel}"
                ev = CameraEvent(camera_name=name, timestamp=time.time())
                events.append(ev)
        except Exception as e:
            errors.log_error("amcrest.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("amcrest", AmcrestCameraProvider)
