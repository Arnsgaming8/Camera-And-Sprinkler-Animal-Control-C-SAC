import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class UnifiCameraProvider(CameraProvider):
    name = "unifi"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_event_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 443))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""
        self._verify_ssl = config.get("verify_ssl", "true").lower() == "true"

    async def connect(self) -> bool:
        try:
            from uiprotect import ProtectApiClient
            self._api = ProtectApiClient(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                verify_ssl=self._verify_ssl,
            )
            await self._api.update()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("unifi.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            await self._api.update()
            for camera_id, camera in self._api.bootstrap.cameras.items():
                try:
                    last_motion = getattr(camera, "last_motion_event_id", None)
                    is_motion = getattr(camera, "is_motion_detected", False)
                    if last_motion and last_motion not in self._last_event_ids:
                        self._last_event_ids.add(last_motion)
                        name = f"unifi_{camera.name}"
                        ev = CameraEvent(camera_name=name, timestamp=time.time())
                        events.append(ev)
                    elif is_motion:
                        event_id = f"{camera_id}_{time.time()}"
                        if event_id not in self._last_event_ids:
                            self._last_event_ids.add(event_id)
                            name = f"unifi_{camera.name}"
                            ev = CameraEvent(camera_name=name, timestamp=time.time())
                            events.append(ev)
                except Exception as e:
                    errors.log_error("unifi.check_motion.camera", str(e))
        except Exception as e:
            errors.log_error("unifi.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("unifi", UnifiCameraProvider)
