import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class FoscamCameraProvider(CameraProvider):
    name = "foscam"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_alarm_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 88))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from libpyfoscam import FoscamCamera
            self._api = FoscamCamera(self._host, self._port, self._username, self._password, is_int=False)
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("foscam.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            alarms = await self._api.get_alarm_record()
            count = alarms.get("count", 0)
            if count > 0:
                records = alarms.get("info", [])
                if not isinstance(records, list):
                    records = [records]
                for rec in records:
                    alarm_id = str(rec.get("index", ""))
                    if alarm_id and alarm_id not in self._last_alarm_ids:
                        self._last_alarm_ids.add(alarm_id)
                        name = f"foscam_{self._host}"
                        ev = CameraEvent(camera_name=name, timestamp=time.time())
                        events.append(ev)
        except Exception as e:
            errors.log_error("foscam.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._api = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("foscam", FoscamCameraProvider)
