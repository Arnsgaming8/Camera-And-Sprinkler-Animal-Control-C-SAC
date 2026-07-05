import asyncio
import time
from collections import deque

import aiohttp

import errors
from . import CameraProvider, CameraEvent, register


class RtspCameraProvider(CameraProvider):
    name = "rtsp"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self._connected = False
        self._cap = None
        self._last_motion_time: float = 0
        self._cooldown = int(config.get("cooldown_seconds", 30))
        self._url = config.get("url") or config.get("rtsp_url") or ""
        self._username = config.get("username") or config.get("email") or ""
        self._password = config.get("password") or ""
        self._threshold = float(config.get("motion_threshold", 5000))

    async def connect(self) -> bool:
        if not self._url:
            errors.log_error("rtsp.connect", "No RTSP URL provided")
            return False
        try:
            import cv2
            full_url = self._url
            if self._username and self._password:
                from urllib.parse import urlparse, urlunparse
                parsed = urlparse(self._url)
                full_url = parsed._replace(
                    netloc=f"{self._username}:{self._password}@{parsed.hostname}:{parsed.port or 554}"
                ).geturl()
            self._cap = cv2.VideoCapture(full_url, cv2.CAP_FFMPEG)
            if not self._cap.isOpened():
                errors.log_error("rtsp.connect", "Failed to open RTSP stream")
                return False
            self._connected = True
            return True
        except Exception as e:
            errors.log_error("rtsp.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []
        if not self._connected or self._cap is None:
            return events
        try:
            import cv2
            import numpy as np
            ret, frame = await asyncio.get_event_loop().run_in_executor(None, self._cap.read)
            if not ret or frame is None:
                return events
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            if not hasattr(self, "_bg") or self._bg is None:
                self._bg = gray.astype(np.float32)
                return events
            cv2.accumulateWeighted(gray, self._bg, 0.5)
            diff = cv2.absdiff(gray, cv2.convertScaleAbs(self._bg))
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            motion_area = sum(cv2.contourArea(c) for c in contours)
            now = time.time()
            if motion_area > self._threshold and (now - self._last_motion_time) > self._cooldown:
                self._last_motion_time = now
                name = f"rtsp_cam"
                ev = CameraEvent(camera_name=name, timestamp=now)
                events.append(ev)
        except Exception as e:
            pass
        return events

    async def disconnect(self):
        self._connected = False
        if self._cap is not None:
            try:
                import cv2
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("rtsp", RtspCameraProvider)
