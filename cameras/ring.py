import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class RingCameraProvider(CameraProvider):
    name = "ring"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._ring = None
        self._last_event_ids: set[str] = set()
        email = config.get("email") or config.get("ring_email") or ""
        password = config.get("password") or config.get("ring_password") or ""
        self._email = email
        self._password = password

    async def connect(self) -> bool:
        try:
            from ring_doorbell import Auth, Ring
            self._auth = Auth(f"BABBS/1.0", http_client_session=self._session)
            await self._auth.async_fetch_token(self._email, self._password)
            self._ring = Ring(self._auth)
            await self._ring.async_update_data()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("ring.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._ring:
            return events
        try:
            await self._ring.async_update_data()
            for device in list(self._ring.devices.get("stickup_cams", [])) + list(self._ring.devices.get("doorbots", [])):
                try:
                    last_event = getattr(device, "last_event", None)
                    if last_event:
                        event_id = str(getattr(last_event, "created_at", "")) + str(device.id)
                        if event_id not in self._last_event_ids:
                            self._last_event_ids.add(event_id)
                            name = getattr(device, "name", f"ring_{device.id}")
                            ts = time.time()
                            ev = CameraEvent(camera_name=name, timestamp=ts)
                            events.append(ev)
                except Exception as e:
                    errors.log_error("ring.check_motion.device", str(e))
        except Exception as e:
            errors.log_error("ring.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._ring = None
        self._auth = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("ring", RingCameraProvider)
