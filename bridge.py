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


def load_config():
    path = os.path.join(os.path.dirname(__file__), "config.yml")
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
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yml")


def _save_blink_auth(auth):
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


async def _sync_blink_auth_to_render():
    raw = os.environ.get("BLINK_AUTH")
    if not raw:
        return
    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        print("  RENDER_API_KEY not set — blink auth won't survive deploy")
        return
    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
    if not service_id:
        print("  RENDER_SERVICE_ID not found — blink auth won't survive deploy")
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(
                f"https://api.render.com/v1/services/{service_id}/env-vars/BLINK_AUTH",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"key": "BLINK_AUTH", "value": raw},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"  Failed to sync blink auth to Render: {resp.status} {text[:200]}")
                else:
                    print("  Blink auth synced to Render env var")
    except Exception as e:
        print(f"  Failed to sync blink auth to Render: {e}")


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


def load_last_motion():
    try:
        with open(LAST_MOTION_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        errors.log_error("load_last_motion", f"Cannot read motion file: {e}", exc_info=True)
        return None


def save_last_motion(ts):
    try:
        with open(LAST_MOTION_FILE, "w") as f:
            f.write(ts)
    except Exception as e:
        errors.log_error("save_last_motion", f"Cannot write motion file: {e}", exc_info=True)


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
        payload = {
            "session": {
                "email": CONFIG["bhyve_email"],
                "password": CONFIG["bhyve_password"],
            }
        }
        try:
            async with self.session.post(f"{BHYVE_API}/session", json=payload) as r:
                data = await r.json()
                if r.status >= 400:
                    raise RuntimeError(
                        f"B-hyve login failed ({r.status}): {data.get('error', data)}"
                    )
                self.token = data["orbit_session_token"]
        except KeyError as e:
            raise RuntimeError(f"B-hyve login response missing field: {e}") from e
        except aiohttp.ClientError as e:
            raise RuntimeError(f"B-hyve login network error: {e}") from e

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
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            minutes = max(1, round(minutes))
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [{"station": zone, "run_time": minutes}],
            }
            await self.ws.send_json(payload)
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
            await self.ws.send_json(payload)
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
                ts = datetime.now().strftime("%I:%M:%S %p")
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
    """Submit a 2FA pin and complete authentication. Returns True on success."""
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
        await blink.get_homescreen()
        await blink.setup_post_verify()
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

            blink = Blink()
            try:
                auth_data = {
                    "username": CONFIG["blink_email"],
                    "password": CONFIG["blink_password"],
                }
                auth_data.update(_load_blink_auth())
                blink.auth = Auth(auth_data, session=session)
                if not await blink.start():
                    msg = "Blink login failed. Check credentials or rate-limited. Retrying..."
                    print(f"  {msg}")
                    errors.log_error("main.blink_setup", msg)
                    retry = 60
                    while True:
                        await asyncio.sleep(retry)
                        print(f"  Retrying Blink login in {retry}s...")
                        try:
                            if await blink.start():
                                state.active_blink = blink
                                _save_blink_auth(blink.auth)
                                print("  Blink login successful on retry")
                                await _sync_blink_auth_to_render()
                                break
                        except BlinkTwoFARequiredError:
                            raise
                        except Exception:
                            pass
                        retry = min(retry * 2, 3600)
                else:
                    state.active_blink = blink
                    _save_blink_auth(blink.auth)
                    await _sync_blink_auth_to_render()
            except BlinkTwoFARequiredError:
                msg = (
                    "Blink requires two-factor authentication. "
                    "A verification code has been sent to your email. "
                    "Submit it at the dashboard."
                )
                print(f"  2FA REQUIRED: {msg}")
                errors.log_error("main.blink_2fa", msg)
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
                        _save_blink_auth(blink.auth)
                        await _sync_blink_auth_to_render()
                        errors.log_error("main.blink_2fa", "2FA completed successfully")
                        print("  2FA completed successfully")
                        break
                    except Exception as e:
                        errors.log_error("main.blink_2fa_key", f"Exception: {e}", exc_info=True)
                        print(f"  ERROR: 2FA submission failed: {e}")
                        state.blink_instance = blink
            except Exception as e:
                errors.log_error("main.blink_setup", str(e), exc_info=True)
                print(f"  ERROR: Blink setup failed: {e}")
                return

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
