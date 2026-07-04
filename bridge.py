import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp
import yaml
from blinkpy.blinkpy import Blink
from blinkpy.auth import Auth, BlinkTwoFARequiredError

import errors
import state

# --- Monkey-patches for blinkpy (shipped to Render) ---
import blinkpy.api as _bapi

# Patch 1: oauth_signin — accept HTTP 202 alongside legacy 412 for 2FA
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
    data = {
        "username": email,
        "password": password,
        "csrf-token": csrf_token,
    }
    response = await auth.session.post(
        OAUTH_SIGNIN_URL, headers=headers, data=data, allow_redirects=False
    )
    status = response.status
    if status in (412, 202):
        return "2FA_REQUIRED"
    if status == 302:
        return "SUCCESS"
    if status == 429:
        import json
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

# Patch 2: check_new_video_time — use motion_interval window not last_refresh
import blinkpy.sync_module as _sm
_orig_check = _sm.BlinkSyncModule.check_new_video_time

def _patched_check_time(self, timestamp, reference=None):
    from blinkpy.helpers.util import time_to_seconds
    if not reference:
        return time_to_seconds(timestamp) > self.blink.last_refresh - self.motion_interval * 60
    return time_to_seconds(timestamp) > time_to_seconds(reference)

_sm.BlinkSyncModule.check_new_video_time = _patched_check_time

# Patch 3: request_videos — no-op pass-through (retained for future patches)
import blinkpy.api as _api
_orig_request_videos = _api.request_videos

async def _patched_request_videos(blink, time=None, page=0):
    return await _orig_request_videos(blink, time=time, page=page)

_api.request_videos = _patched_request_videos

# Patch 4: get_time — use fromtimestamp(..., tz=utc) for Python 3.14 compat
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


def load_config():
    path = state.get_config_path()
    example_path = os.path.join(os.path.dirname(__file__), "config.example.yml")
    try:
        if not os.path.exists(path):
            msg = f"Config file not found at {path}. Create it from {example_path}"
            print(msg)
            errors.log_error("load_config", msg)
            sys.exit(1)
        with open(path) as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"Invalid YAML in config file: {e}"
        print(msg)
        errors.log_error("load_config", msg)
        sys.exit(1)
    except Exception as e:
        msg = f"Unexpected error loading config: {e}"
        print(msg)
        errors.log_error("load_config", msg, exc_info=True)
        sys.exit(1)


CONFIG = load_config()

try:
    DURATION_SECONDS = CONFIG.get("duration_seconds", CONFIG.get("duration_minutes", 5) * 60)
    if not isinstance(DURATION_SECONDS, (int, float)) or DURATION_SECONDS <= 0:
        raise ValueError(f"Invalid duration: {DURATION_SECONDS}")
except Exception as e:
    msg = f"Invalid duration config: {e}"
    print(msg)
    errors.log_error("config.duration", msg, exc_info=True)
    DURATION_SECONDS = 300

BHYVE_API = "https://api.orbitbhyve.com/v1"
LAST_MOTION_FILE = os.path.join(os.path.dirname(__file__), ".last_motion")
CONFIG_PATH = state.get_config_path()


async def _save_blink_auth(auth):
    import json
    login_data = auth.login_attributes
    data = {k: login_data.get(k) for k in ("refresh_token", "hardware_id", "host", "region_id", "account_id", "user_id")}
    data = {k: v for k, v in data.items() if v is not None}
    if not data:
        return
    os.environ["BLINK_AUTH"] = json.dumps(data)
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        cfg["blink_auth"] = data
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        print("  Blink auth saved to config.yml")
    except Exception as e:
        print(f"  Failed to save blink auth to config.yml: {e}")

    api_key = os.environ.get("RENDER_API_KEY") or CONFIG.get("render_api_key")
    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
    if api_key and service_id:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
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
    elif api_key and not service_id:
        print("  RENDER_SERVICE_ID not set — cannot persist auth via Render API")


def _load_blink_auth():
    import json
    raw = os.environ.get("BLINK_AUTH")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH)) or {}
        return cfg.get("blink_auth", {})
    except Exception:
        return {}


POLL_INTERVAL = CONFIG.get("poll_interval_seconds", 30)
if not isinstance(POLL_INTERVAL, (int, float)) or POLL_INTERVAL < 1:
    print("Invalid poll_interval_seconds, defaulting to 30")
    POLL_INTERVAL = 30

DISABLE_BLINK = CONFIG.get("disable_blink_polling", False) or os.environ.get("DISABLE_BLINK_POLLING") == "1"

raw_cameras = CONFIG.get("cameras")
if raw_cameras is not None and len(raw_cameras) > 0:
    CAMERAS = []
    for c in raw_cameras:
        CAMERAS.append({
            "name": c["name"],
            "zone": int(c["zone"]),
            "duration_seconds": int(c.get("duration_seconds", DURATION_SECONDS)),
            "arm": c.get("arm", True),
            "no_water": c.get("no_water", False),
        })
elif raw_cameras is None:
    CAMERAS = [{
        "name": CONFIG.get("camera_name", "?"),
        "zone": int(CONFIG.get("zone_number", 1)),
        "duration_seconds": DURATION_SECONDS,
        "arm": True,
        "no_water": False,
    }]
else:
    CAMERAS = []


BHYVE_WS = "wss://api.orbitbhyve.com/v1/events"
PING_INTERVAL = 25


class BHyveClient:
    def __init__(self, session):
        self.session = session
        self.token = None
        self.ws = None
        self._ping_task = None
        self._token_for_ws = None
        self.device_id = CONFIG["device_id"]

    async def login(self):
        import json as _json
        payload = {
            "session": {
                "email": CONFIG["bhyve_email"],
                "password": CONFIG["bhyve_password"],
            }
        }
        for attempt in range(3):
            try:
                async with self.session.post(f"{BHYVE_API}/session", json=payload) as r:
                    text = await r.text()
                    if r.status >= 500:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise RuntimeError(f"B-hyve login failed ({r.status}): {text[:200]}")
                    if r.status >= 400:
                        raise RuntimeError(f"B-hyve login failed ({r.status}): {text[:200]}")
                    try:
                        data = _json.loads(text)
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise
                    self.token = data["orbit_session_token"]
                    return
            except aiohttp.ClientError as e:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"B-hyve login network error: {e}") from e
            except KeyError as e:
                raise RuntimeError(f"B-hyve login response missing field: {e}") from e

    async def connect_ws(self):
        if self.ws and not self.ws.closed and self._token_for_ws == self.token:
            return
        if self.ws and not self.ws.closed:
            await self.ws.close()
        self.ws = None
        self.ws = await self.session.ws_connect(BHYVE_WS)
        self._token_for_ws = self.token
        await self.ws.send_json({"event": "app_connection", "orbit_session_token": self.token})

    async def _ping_loop(self):
        try:
            while self.ws and not self.ws.closed:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await self.ws.send_json({"event": "ping"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def start_zone(self, zone, minutes):
        try:
            await self.connect_ws()
            minutes = max(1, round(minutes))
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [{"station": zone, "run_time": minutes}],
            }
            await self._send_ws_json(payload)
            started = False
            for _ in range(10):
                try:
                    msg = await asyncio.wait_for(self.ws.receive(), timeout=3)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.json()
                        ev = data.get("event")
                        if ev == "change_mode" or ev == "watering_in_progress_notification":
                            started = True
                            break
                except asyncio.TimeoutError:
                    break
            if not started:
                raise RuntimeError("No confirmation from server (change_mode not echoed)")
            if self._ping_task is None or self._ping_task.done():
                self._ping_task = asyncio.ensure_future(self._ping_loop())
        except Exception as e:
            raise RuntimeError(f"Start zone failed: {e}") from e

    async def _send_ws_json(self, payload):
        try:
            await self.ws.send_json(payload)
        except (aiohttp.ClientConnectionResetError, aiohttp.ClientError):
            self.ws = None
            self._token_for_ws = None
            await self.connect_ws()
            await self.ws.send_json(payload)

    async def stop_zone(self):
        try:
            await self.connect_ws()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [],
            }
            await self._send_ws_json(payload)
        except Exception as e:
            raise RuntimeError(f"Stop zone failed: {e}") from e


class BlinkWatcher:
    def __init__(self, blink, bhyve):
        self.blink = blink
        self.bhyve = bhyve
        self.last_records = {}
        self.last_watered = {}
        for cam in CAMERAS:
            self.last_records[cam["name"]] = None
            self.last_watered[cam["zone"]] = 0

    async def water_for_duration(self, zone, secs):
        if not self.bhyve.token:
            try:
                await self.bhyve.login()
            except Exception as e:
                errors.log_error("water_for_duration.login", str(e), exc_info=True)
                print(f"  ERROR: B-hyve login before watering failed: {e}")
                return

        minutes = max(secs / 60, 1 / 60)
        try:
            await self.bhyve.start_zone(zone, minutes)
            msg = f"Zone {zone} watering started ({secs}s)"
            print(f"  {msg}")
            errors.log_error("watering", msg)
        except Exception as e:
            errors.log_error("water_for_duration.start_zone", str(e), exc_info=True)
            print(f"  ERROR: Starting zone {zone} failed: {e}")
            self.bhyve.token = None
            return

        try:
            await asyncio.sleep(secs)
        except asyncio.CancelledError:
            print("  Watering interrupted")
            errors.log_error("watering", f"Zone {zone} watering interrupted")
        except Exception as e:
            errors.log_error("water_for_duration.sleep", f"Sleep error: {e}", exc_info=True)

        try:
            await self.bhyve.stop_zone()
            msg = f"Zone {zone} watering stopped"
            print(f"  {msg}")
            errors.log_error("watering", msg)
        except Exception as e:
            errors.log_error("water_for_duration.stop_zone", str(e), exc_info=True)
            print(f"  ERROR: Stopping zone {zone} failed: {e}")

    async def _handle_2fa_background(self):
        state.blink_instance = self.blink
        state.twofa_pending = False
        try:
            while True:
                if state.blink.urls is not None:
                    state.blink_instance = None
                    break
                if not state.twofa_pending:
                    await asyncio.sleep(1)
                    continue
                pin = state.twofa_pin
                state.twofa_pin = None
                state.twofa_pending = False
                try:
                    ok = await process_2fa_code(self.blink, pin)
                    if ok:
                        state.blink_instance = None
                        state.active_blink = self.blink
                        await _save_blink_auth(self.blink.auth)
                        print("  2FA re-authentication successful")
                        break
                except Exception as e:
                    errors.log_error("check_motion.2fa", f"Re-auth exception: {e}", exc_info=True)
                    state.blink_instance = self.blink
        finally:
            state.reauth_in_progress = False

    async def check_motion(self):
        state.last_poll = datetime.now(timezone.utc).isoformat()
        if self.blink.urls is None:
            if state.reauth_in_progress:
                print("  Re-auth already in progress, skipping")
                return
            now = time.time()
            if now - getattr(self, "_last_reauth_attempt", 0) < 30:
                return
            self._last_reauth_attempt = now
            try:
                ok = await self.blink.start()
                if not ok:
                    errors.log_error("check_motion.reauth", "Blink login failed (check credentials or Blink rate-limit)")
                    print("  Blink start returned False (login failed)")
                    return
            except BlinkTwoFARequiredError:
                errors.log_error("check_motion.2fa_required", "Blink session expired — enter code on dashboard")
                print("  Blink session expired, 2FA required")
                state.reauth_in_progress = True
                asyncio.ensure_future(self._handle_2fa_background())
            except Exception as e:
                errors.log_error("check_motion.reauth", str(e), exc_info=True)
                print(f"  Blink re-auth failed: {e}")
            return
        try:
            await self.blink.refresh()
        except Exception as e:
            errors.log_error("check_motion.refresh", str(e), exc_info=True)
            print(f"  ERROR: Blink refresh failed: {e}")
            return

        for cam in CAMERAS:
            name = cam["name"]
            zone = cam["zone"]
            secs = cam["duration_seconds"]
            try:
                camera = self.blink.cameras.get(name)
                if camera is None:
                    names = list(self.blink.cameras.keys())
                    msg = f"Camera '{name}' not found. Available: {names}"
                    print(msg)
                    errors.log_error("check_motion.camera", msg)
                    continue
            except Exception as e:
                errors.log_error("check_motion.camera", f"Error accessing '{name}': {e}", exc_info=True)
                print(f"  ERROR: Accessing camera '{name}' failed: {e}")
                continue

            blink_armed = bool(getattr(camera, "arm", True))
            if cam.get("arm") != blink_armed:
                if not cam.get("arm") and blink_armed:
                    self.last_records[name] = None
            armed = cam.get("arm", True)
            print(f"  Camera '{name}': armed={armed}, camera.arm={blink_armed}, last_record={'set' if camera.last_record else None}, motion={camera.motion_detected}")

            if not armed:
                print(f"  Skipping '{name}' — camera is disarmed")
                if camera.last_record:
                    self.last_records[name] = camera.last_record
                continue

            if cam.get("no_water", False):
                print(f"  Motion on '{name}' — no_water enabled, skipping sprinklers")
                if camera.last_record:
                    self.last_records[name] = camera.last_record
                continue

            cooldown = max(POLL_INTERVAL, secs + 5)
            if time.time() - self.last_watered.get(zone, 0) < cooldown:
                remaining = cooldown - (time.time() - self.last_watered.get(zone, 0))
                print(f"  Skipping '{name}' — cooldown {remaining:.0f}s left for zone {zone}")
                continue

            record_now = camera.last_record
            prev = self.last_records.get(name)
            motion_now = camera.motion_detected
            print(f"  Check trigger: record_now={'set' if record_now else None}, prev={'set' if prev else None}, motion={motion_now}")

            trigger = False
            if record_now and record_now != prev:
                self.last_records[name] = record_now
                trigger = True
                reason = "new clip"
            elif motion_now:
                trigger = True
                reason = "motion flag"
            else:
                print(f"  No trigger: record_now unchanged{' (' + str(record_now)[:20] + ')' if record_now else ' (None)'}, motion=False")

            if trigger:
                self.last_watered[zone] = time.time()
                ts = datetime.now().strftime("%m/%d/%Y-%I:%M-%p")
                msg = f"[{ts}] {reason} on '{name}' → zone {zone} ({secs}s)"
                print(msg)
                errors.log_error("motion", msg)
                await self.water_for_duration(zone, secs)

    async def run(self):
        while True:
            try:
                await self.check_motion()
            except Exception as e:
                errors.log_error("run.main_loop", str(e), exc_info=True)
                print(f"  ERROR in main loop: {e}")
            await asyncio.sleep(POLL_INTERVAL)


async def process_2fa_code(blink, pin):
    from blinkpy import api as blink_api
    auth = blink.auth
    has_csrf = hasattr(auth, "_oauth_csrf_token")
    has_ver = hasattr(auth, "_oauth_code_verifier")
    if not has_csrf or not has_ver:
        errors.log_error("blink_2fa_key", f"OAuth state missing (csrf={has_csrf}, verifier={has_ver}) — click Resend")
        print("  OAuth state missing — click Resend Code first")
        return False
    csrf = auth._oauth_csrf_token
    verifier = auth._oauth_code_verifier
    print("  Verifying 2FA code...")
    ok = await blink_api.oauth_verify_2fa(auth, csrf, pin)
    if not ok:
        errors.log_error("blink_2fa_key", "oauth_verify_2fa returned False (wrong/expired code)")
        print("  Code rejected by Blink. Check the code and try again.")
        return False
    print("  Getting authorization code...")
    code = await blink_api.oauth_get_authorization_code(auth)
    if not code:
        errors.log_error("blink_2fa_key", "oauth_get_authorization_code returned None")
        print("  Failed to get auth code. Try Resend Code.")
        return False
    print("  Exchanging code for token...")
    token_data = await blink_api.oauth_exchange_code_for_token(auth, code, verifier, auth.hardware_id)
    if not token_data:
        errors.log_error("blink_2fa_key", "oauth_exchange_code_for_token returned None")
        print("  Failed to exchange code. Try Resend Code.")
        return False
    await auth._process_token_data(token_data)
    try:
        blink.setup_urls()
        for attempt in range(3):
            try:
                await blink.get_homescreen()
                await blink.setup_post_verify()
                break
            except Exception:
                if attempt < 2:
                    print(f"  Blink API error, retrying setup... ({attempt+1})")
                    await asyncio.sleep(3)
                else:
                    raise
    except Exception as e:
        errors.log_error("blink_2fa_key", f"Post-2FA setup failed: {e}", exc_info=True)
        print(f"  Post-2FA setup failed: {e}")
        return False
    finally:
        if hasattr(auth, "_oauth_csrf_token"):
            delattr(auth, "_oauth_csrf_token")
        if hasattr(auth, "_oauth_code_verifier"):
            delattr(auth, "_oauth_code_verifier")
    return True


async def main():
    print("Starting Blink → B-hyve bridge")
    for cam in CAMERAS:
        print(f"  {cam['name']} → zone {cam['zone']} ({cam['duration_seconds']}s)")
    print(f"  Poll every: {POLL_INTERVAL}s")
    print(f"  Errors:     http://localhost:{os.environ.get('ERROR_PORT', 5000)}")

    if DISABLE_BLINK:
        print("  Blink polling disabled (ESP32 handles motion detection)")
        print("  Bridge idle — waiting for ESP32 triggers...")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            print("Bridge stopped")
        return

    try:
        async with aiohttp.ClientSession() as session:
            bhyve = BHyveClient(session)

            blink = Blink(motion_interval=360)
            auth_data = {
                "username": CONFIG["blink_email"],
                "password": CONFIG["blink_password"],
            }
            auth_data.update(_load_blink_auth())
            blink.auth = Auth(auth_data, session=session)

            try:
                login_ok = await blink.start()
            except BlinkTwoFARequiredError:
                login_ok = None

            if login_ok:
                state.active_blink = blink
                await _save_blink_auth(blink.auth)
                print("  Blink login successful")
            elif login_ok is None:
                msg = "Blink requires two-factor authentication."
                print(f"  2FA REQUIRED: {msg}")
                errors.log_error("main.blink_2fa", msg)
            else:
                msg = "Blink login failed. Check credentials or rate-limited."
                print(f"  {msg}")
                errors.log_error("main.blink_setup", msg)
                retry = 60
                for attempt in range(5):
                    await asyncio.sleep(retry)
                    print(f"  Retry {attempt + 1}...")
                    try:
                        if await blink.start():
                            state.active_blink = blink
                            await _save_blink_auth(blink.auth)
                            print("  Blink login successful on retry")
                            break
                    except BlinkTwoFARequiredError:
                        msg = "Blink requires 2FA."
                        print(f"  2FA REQUIRED: {msg}")
                        errors.log_error("main.blink_2fa", msg)
                        break
                    except Exception:
                        pass
                    retry = min(retry * 2, 3600)

            if not state.active_blink:
                state.blink_instance = blink
                state.twofa_pending = False
                print("  Waiting for 2FA code via dashboard...")
                while True:
                    if not state.twofa_pending:
                        await asyncio.sleep(1)
                        continue
                    pin = state.twofa_pin
                    state.twofa_pin = None
                    state.twofa_pending = False
                    print("  Submitting 2FA code...")
                    try:
                        ok = await process_2fa_code(blink, pin)
                        if not ok:
                            continue
                        state.blink_instance = None
                        state.active_blink = blink
                        await _save_blink_auth(blink.auth)
                        errors.log_error("main.blink_2fa", "2FA completed successfully")
                        print("  2FA completed successfully")
                        break
                    except Exception as e:
                        errors.log_error("main.blink_2fa_key", f"Exception: {e}", exc_info=True)
                        print(f"  ERROR: 2FA submission failed: {e}")
                        state.blink_instance = blink

            available = list(blink.cameras.keys())
            print(f"  Available cameras: {available}")
            watcher = BlinkWatcher(blink, bhyve)
            await watcher.run()
    except asyncio.CancelledError:
        print("Bridge stopped")
    except Exception as e:
        errors.log_error("main", str(e), exc_info=True)
        print(f"  FATAL: {e}")
        raise


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBridge stopped by user")
    except Exception as e:
        errors.log_error("main.startup", str(e), exc_info=True)
        print(f"FATAL: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run()
