import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class AxisCameraProvider(CameraProvider):
    name = "axis"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._device = None
        self._last_event_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from axis import AxisDevice
            self._device = AxisDevice(
                f"http://{self._host}:{self._port}",
                username=self._username,
                password=self._password,
            )
            await self._device.vapix.initialize()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("axis.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._device:
            return events
        try:
            await self._device.vapix.initialize()
            if hasattr(self._device.vapix, "mqtt"):
                mqtt = self._device.vapix.mqtt
                client = getattr(mqtt, "client", None)
                if client:
                    messages = mqtt.get_messages()
                    for msg in messages:
                        topic = msg.get("topic", "")
                        if "motion" in topic.lower():
                            msg_id = str(msg.get("message", "")) + str(msg.get("timestamp", ""))
                            if msg_id not in self._last_event_ids:
                                self._last_event_ids.add(msg_id)
                                name = f"axis_{self._host}"
                                ev = CameraEvent(camera_name=name, timestamp=time.time())
                                events.append(ev)
        except Exception as e:
            errors.log_error("axis.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        self._device = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("axis", AxisCameraProvider)
