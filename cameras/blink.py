import asyncio
import json
import os
import time
from datetime import datetime, timezone

import aiohttp
import yaml
from blinkpy.blinkpy import Blink
from blinkpy.auth import Auth, BlinkTwoFARequiredError

import errors
import state
from state import get_config_path
from . import CameraProvider, CameraEvent, register

# --- Monkey-patches for blinkpy (shipped to Render) ---
import blinkpy.api as _bapi

_orig_signin = _bapi.oauth_signin

async def _patched_signin(auth, email, password, csrf_token):
    from blinkpy.helpers.constants import OAUTH_USER_AGENT, OAUTH_SIGNIN_URL
    headers = {
        "User-Agent": OAUTH_USER_AGENT,
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://api.oauth.blink.com",
        "Referer": OAUTH_SIGNIN_URL,
    }
    data = {"username": email, "password": password, "csrf-token": csrf_token}
    response = await auth.session.post(OAUTH_SIGNIN_URL, headers=headers, data=data, allow_redirects=False)
    status = response.status
    if status in (412, 202):
        return "2FA_REQUIRED"
    if status == 302:
        return "SUCCESS"
    if status == 429:
        body = await response.text()
        try:
            info = json.loads(body)
            wait = int(info.get("next_time_in_secs", 600))
        except Exception:
            wait = 600
        print(f"  RATE LIMITED by Blink. Waiting {wait}s...")
        await asyncio.sleep(wait)
    return None

_bapi.oauth_signin = _patched_signin

import blinkpy.sync_module as _sm

_orig_check = _sm.BlinkSyncModule.check_new_video_time

def _patched_check_time(self, timestamp, reference=None):
    from blinkpy.helpers.util import time_to_seconds
    if not reference:
        return time_to_seconds(timestamp) > self.blink.last_refresh - self.motion_interval * 60
    return time_to_seconds(timestamp) > time_to_seconds(reference)

_sm.BlinkSyncModule.check_new_video_time = _patched_check_time

import blinkpy.helpers.util as _util

_orig_get_time = _util.get_time

def _patched_get_time(time_to_convert=None):
    import datetime as _dt
    if time_to_convert is None:
        time_to_convert = time.time()
    utc_dt = _dt.datetime.fromtimestamp(time_to_convert, tz=_dt.timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S") + "+00:00"

_util.get_time = _patched_get_time
# --- End monkey-patches ---


class BlinkCameraProvider(CameraProvider):
    name = "blink"

    def __init__(self, config: dict, session: aiohttp.ClientSession | None = None):
        self._config = config
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession()
        self.blink: Blink | None = None
        self._connected = False
        self._reauth_in_progress = False
        self._last_reauth_attempt: float = 0
        self._last_motion_names: set[str] = set()

        email = config.get("email") or config.get("blink_email") or ""
        password = config.get("password") or config.get("blink_password") or ""
        self._email = email
        self._password = password
        self._motion_interval = config.get("motion_interval", 360)

    async def _load_auth(self) -> dict:
        raw = os.environ.get("BLINK_AUTH")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        try:
            cfg = yaml.safe_load(open(get_config_path())) or {}
            return cfg.get("blink_auth", {})
        except Exception:
            return {}

    async def _save_auth(self):
        if not self.blink or not self.blink.auth:
            return
        login_data = self.blink.auth.login_attributes
        data = {k: login_data.get(k) for k in ("refresh_token", "hardware_id", "host", "region_id", "account_id", "user_id")}
        data = {k: v for k, v in data.items() if v is not None}
        if not data:
            return
        os.environ["BLINK_AUTH"] = json.dumps(data)
        try:
            with open(get_config_path()) as f:
                cfg = yaml.safe_load(f) or {}
            cfg["blink_auth"] = data
            with open(get_config_path(), "w") as f:
                yaml.dump(cfg, f, default_flow_style=False)
        except Exception as e:
            print(f"  Failed to save blink auth: {e}")

        api_key = os.environ.get("RENDER_API_KEY") or self._config.get("render_api_key")
        service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
        if api_key and service_id:
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.put(
                        f"https://api.render.com/v1/services/{service_id}/env-vars/BLINK_AUTH",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"key": "BLINK_AUTH", "value": json.dumps(data)},
                    ) as resp:
                        if resp.status == 200:
                            print("  Blink auth saved to Render env var")
                        else:
                            text = await resp.text()
                            print(f"  Failed to save blink auth to Render: {resp.status} {text[:200]}")
            except Exception as e:
                print(f"  Failed to save blink auth to Render: {e}")

    async def connect(self) -> bool:
        try:
            blink = Blink(motion_interval=self._motion_interval)
            auth_data = {"username": self._email, "password": self._password}
            auth_data.update(await self._load_auth())
            blink.auth = Auth(auth_data, session=self._session)

            try:
                ok = await blink.start()
            except BlinkTwoFARequiredError:
                state.blink_instance = blink
                state.twofa_pending = False
                print("  Blink requires 2FA — waiting for code via dashboard")
                return False

            if ok:
                self.blink = blink
                self._connected = True
                state.active_blink = blink
                await self._save_auth()
                return True

            print("  Blink login failed, will retry")
            return False

        except BlinkTwoFARequiredError:
            state.blink_instance = blink
            state.twofa_pending = False
            print("  Blink 2FA required during connect")
            return False
        except Exception as e:
            errors.log_error("blink.connect", str(e), exc_info=True)
            return False

    async def check_motion(self) -> list[CameraEvent]:
        events: list[CameraEvent] = []

        # If 2FA completed in background, sync blink instance
        if (not self._connected or not self.blink) and state.active_blink is not None:
            if state.blink_instance is None and state.active_blink is not self.blink:
                self.blink = state.active_blink
                self._connected = True
                print("  Blink 2FA completed — provider synced")

        if not self._connected or not self.blink:
            if self._reauth_in_progress:
                return events
            now = time.time()
            if now - self._last_reauth_attempt < 30:
                return events
            self._last_reauth_attempt = now
            ok = await self.connect()
            if not ok:
                return events

        try:
            await self.blink.refresh()
        except Exception as e:
            errors.log_error("blink.refresh", str(e), exc_info=True)
            if "401" in str(e) or "403" in str(e):
                self._connected = False
            return events

        for camera_name, camera in self.blink.cameras.items():
            try:
                record_now = getattr(camera, "last_record", None)
                motion_now = bool(getattr(camera, "motion_detected", False))

                if record_now or motion_now:
                    ts = 0.0
                    if record_now:
                        try:
                            parsed = datetime.fromisoformat(record_now.replace("Z", "+00:00"))
                            ts = parsed.timestamp()
                        except Exception:
                            ts = time.time()
                    else:
                        ts = time.time()

                    ev = CameraEvent(camera_name=camera_name, timestamp=ts)
                    events.append(ev)
            except Exception as e:
                errors.log_error("blink.check_motion.camera", f"{camera_name}: {e}")

        return events

    async def disconnect(self):
        self._connected = False
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()


register("blink", BlinkCameraProvider)
