import asyncio
import time
import json

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class DahuaCameraProvider(CameraProvider):
    name = "dahua"

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

    async def connect(self) -> bool:
        try:
            from dahua_rpc import RPCClient
            self._api = RPCClient(self._host, self._port, self._username, self._password)
            ok = await self._api.login()
            if ok:
                self._connected = True
                return True
            return False
        except Exception as e:
            errors.log_error("dahua.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            alarms = await self._api.get_alarm_records(1)
            if isinstance(alarms, dict):
                records = alarms.get("records", [])
            elif isinstance(alarms, list):
                records = alarms
            else:
                records = []
            for rec in records:
                event_id = str(rec.get("recno", "")) + str(rec.get("startTime", ""))
                if event_id and event_id not in self._last_event_ids:
                    self._last_event_ids.add(event_id)
                    name = f"dahua_{self._host}"
                    ev = CameraEvent(camera_name=name, timestamp=time.time())
                    events.append(ev)
        except Exception as e:
            errors.log_error("dahua.check_motion", str(e), exc_info=True)
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


register("dahua", DahuaCameraProvider)
