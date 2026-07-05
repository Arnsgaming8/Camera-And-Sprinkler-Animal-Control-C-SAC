import asyncio
import time
from datetime import datetime, timezone

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
        self._api = None
        self._last_event_ids: set[str] = set()
        email = config.get("email") or config.get("ring_email") or ""
        password = config.get("password") or config.get("ring_password") or ""
        self._email = email
        self._password = password

    async def connect(self) -> bool:
        try:
            from ring_doorbell import Ring
            self._api = Ring(self._email, self._password)
            ok = await self._api.async_update_data()
            if ok is None:
                ok = True
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("ring.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            await self._api.async_update_data()
            for device in self._api.devices.get("stickup_cams", []):
                try:
                    event_id = getattr(device, "last_event_id", None) or getattr(device, "id", "")
                    has_motion = getattr(device, "motion_detected", False) or getattr(device, "last_event", None) is not None
                    if has_motion and event_id and event_id not in self._last_event_ids:
                        self._last_event_ids.add(event_id)
                        name = getattr(device, "name", f"ring_{device.id}")
                        ev = CameraEvent(camera_name=name, timestamp=time.time())
                        events.append(ev)
                except Exception as e:
                    errors.log_error("ring.check_motion.device", str(e))
            for device in self._api.devices.get("doorbots", []):
                try:
                    event_id = getattr(device, "last_event_id", None) or getattr(device, "id", "")
                    has_motion = getattr(device, "motion_detected", False) or getattr(device, "last_event", None) is not None
                    if has_motion and event_id and event_id not in self._last_event_ids:
                        self._last_event_ids.add(event_id)
                        name = getattr(device, "name", f"doorbot_{device.id}")
                        ev = CameraEvent(camera_name=name, timestamp=time.time())
                        events.append(ev)
                except Exception as e:
                    errors.log_error("ring.check_motion.device", str(e))
        except Exception as e:
            errors.log_error("ring.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("ring", RingCameraProvider)
