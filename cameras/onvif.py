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
        self._pullpoint = None
        self._subscription = None
        self._last_event_ids: set[str] = set()
        self._host = config.get("host") or ""
        self._port = int(config.get("port", 80))
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""

    async def connect(self) -> bool:
        try:
            from onvif import ONVIFCamera
            self._device = ONVIFCamera(self._host, self._port, self._username, self._password)
            await self._device.update_xaddrs()
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("onvif.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or not self._device:
            return events
        try:
            if self._pullpoint is None:
                from onvif.util import PullPointManager
                self._pullpoint = PullPointManager(self._device)
                await self._pullpoint.create_pullpoint()
            msgs = await self._pullpoint.pull_messages(timeout=2, message_limit=10)
            for msg in msgs:
                prop_set = getattr(msg, "property_set", None) or getattr(msg, "PropertySet", None)
                if prop_set is None:
                    continue
                rule_set = getattr(prop_set, "rule_set", None) or getattr(prop_set, "RuleSet", None)
                if rule_set:
                    for rule in rule_set:
                        if hasattr(rule, "Motion") or (hasattr(rule, "IsMotion") and rule.IsMotion):
                            event_id = str(msg.UtcTime) if hasattr(msg, "UtcTime") else str(time.time())
                            if event_id not in self._last_event_ids:
                                self._last_event_ids.add(event_id)
                                name = f"onvif_{self._host}"
                                ts = msg.UtcTime.timestamp() if hasattr(msg, "UtcTime") else time.time()
                                ev = CameraEvent(camera_name=name, timestamp=ts)
                                events.append(ev)
        except Exception as e:
            pass
        return events

    async def disconnect(self):
        self._connected = False
        if self._pullpoint:
            try:
                await self._pullpoint.release()
            except Exception:
                pass
            self._pullpoint = None
        self._device = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("onvif", OnvifCameraProvider)
