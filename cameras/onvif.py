import asyncio
import time

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class OnvifCameraProvider(CameraProvider):
    name = "onvif"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._device = None
        self._media = None
        self._last_motion_time: float = 0
        self._cooldown = int(config.get("cooldown_seconds", 30))
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from onvif import ONVIFCamera
            self._device = ONVIFCamera(self._host, self._port, self._username, self._password)
            await self._device.update_xaddrs()
            self._media = self._device.create_media_service()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("onvif.connect", str(e), exc_info=True)
            return False

    async def _get_motion_snapshot(self):
        """Take a snapshot and signal motion if we can reach the camera."""
        try:
            from onvif import ONVIFCamera
            profiles = await self._media.GetProfiles()
            if not profiles:
                return False
            profile_token = profiles[0].token
            uri = await self._media.GetStreamUri({"Stream": "RTP-Unicast", "Protocol": "RTSP"}, profile_token)
            return True
        except Exception:
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._device:
            return events
        try:
            from onvif import ONVIFCamera
            events_service = self._device.create_events_service()
            pull_point = await events_service.CreatePullPointSubscription()
            try:
                msgs = await pull_point.PullMessages({"Timeout": "PT2S", "MessageLimit": 10})
            except Exception:
                return events
            current_time = time.time()
            for msg in getattr(msgs, "NotificationMessage", []) or []:
                try:
                    prop_set = msg.Message.Data.SimpleItem
                    if isinstance(prop_set, list):
                        for item in prop_set:
                            if getattr(item, "Name", "").endswith("Motion") or getattr(item, "Value", "0") == "1":
                                if current_time - self._last_motion_time > self._cooldown:
                                    self._last_motion_time = current_time
                                    name = f"onvif_{self._host}"
                                    ev = CameraEvent(camera_name=name, timestamp=current_time)
                                    events.append(ev)
                except Exception:
                    pass
        except Exception as e:
            pass
        return events

    async def disconnect(self):
        self._connected = False
        self._device = None
        self._media = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("onvif", OnvifCameraProvider)
