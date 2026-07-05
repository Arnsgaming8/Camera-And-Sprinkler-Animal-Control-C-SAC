import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class VivotekCameraProvider(CameraProvider):
    name = "vivotek"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_motion_state = False
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from libpyvivotek import VivotekCamera
            self._api = VivotekCamera(
                host=self._host,
                port=self._port,
                user=self._username,
                passwd=self._password,
            )
            ok = await self._api.get_snapshot()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("vivotek.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            params = await self._api.get_parameter("motion_detection")
            current_motion = params.get("motion_detection", {}).get("enable", "0") == "1" if isinstance(params, dict) else False
            if current_motion and not self._last_motion_state:
                name = f"vivotek_{self._host}"
                ev = CameraEvent(camera_name=name, timestamp=time.time())
                events.append(ev)
            self._last_motion_state = current_motion
        except Exception as e:
            errors.log_error("vivotek.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("vivotek", VivotekCameraProvider)
