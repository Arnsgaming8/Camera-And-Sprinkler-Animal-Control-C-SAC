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
            from pyunifiprotect import ProtectApiClient
            from pyunifiprotect.data import StateType
            self._api = ProtectApiClient(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                verify_ssl=self._verify_ssl,
            )
            await self._api.get_bootstrap()
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
            events_data = await self._api.get_events(limit=10)
            for ev in events_data:
                if hasattr(ev, "type") and ev.type in ("motion", "smartDetectZone", "ring"):
                    event_id = ev.id if hasattr(ev, "id") else str(ev.start)
                    if event_id not in self._last_event_ids:
                        self._last_event_ids.add(event_id)
                        camera_name = f"unifi_cam"
                        if hasattr(ev, "camera") and ev.camera:
                            camera_name = f"unifi_{ev.camera.name}"
                        ts = ev.start.timestamp() if hasattr(ev, "start") else time.time()
                        evt = CameraEvent(camera_name=camera_name, timestamp=ts)
                        events.append(evt)
        except Exception as e:
            errors.log_error("unifi.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("unifi", UnifiCameraProvider)
