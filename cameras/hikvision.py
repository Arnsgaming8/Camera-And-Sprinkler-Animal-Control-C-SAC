import asyncio
import time
from urllib.parse import urlparse

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class HikvisionCameraProvider(CameraProvider):
    name = "hikvision"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._api = None
        self._last_alert_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""
        self._channel = int(config.get("channel", 1))

    async def connect(self) -> bool:
        try:
            from hikvisionapi import Client
            if self._port != 80:
                base = f"http://{self._host}:{self._port}"
            else:
                base = f"http://{self._host}"
            self._api = Client(base, self._username, self._password)
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("hikvision.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._api:
            return events
        try:
            result = await self._api.EventManager.notification_alert_stream(
                method="POST",
                data={
                    "EventManager": {
                        "notificationAlertStreaming": {
                            "plan": "notSupported"
                        }
                    }
                }
            )
            alerts = result.get("EventManager", {}).get("notificationAlertStreaming", {})
            alert_list = alerts.get("NotificationList", {}).get("NotificationAlert", [])
            if not isinstance(alert_list, list):
                alert_list = [alert_list]
            for alert in alert_list:
                event_type = alert.get("eventType", "")
                if "motion" in event_type.lower() or "VMD" in event_type:
                    alert_id = str(alert.get("dateTime", "")) + str(alert.get("eventType", ""))
                    if alert_id not in self._last_alert_ids:
                        self._last_alert_ids.add(alert_id)
                        name = f"hikvision_{self._host}_ch{self._channel}"
                        ev = CameraEvent(camera_name=name, timestamp=time.time())
                        events.append(ev)
        except Exception as e:
            errors.log_error("hikvision.check_motion", str(e), exc_info=True)
        return events

    async def disconnect(self):
        self._connected = False
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("hikvision", HikvisionCameraProvider)
