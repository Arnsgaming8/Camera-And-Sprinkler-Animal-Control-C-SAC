import asyncio
import os
import sys
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

POLL_INTERVAL = CONFIG.get("poll_interval_seconds", 30)
if not isinstance(POLL_INTERVAL, (int, float)) or POLL_INTERVAL < 1:
    print(f"Invalid poll_interval_seconds, defaulting to 30")
    POLL_INTERVAL = 30


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
        self.zone = CONFIG["zone_number"]

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

    async def start_zone(self, minutes):
        try:
            await self.connect_ws()
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            minutes = max(1, round(minutes))
            payload = {
                "event": "change_mode",
                "mode": "manual",
                "device_id": self.device_id,
                "timestamp": ts,
                "stations": [{"station": self.zone, "run_time": minutes}],
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
        self.last_record = load_last_motion()

    async def water_for_duration(self):
        secs = DURATION_SECONDS
        zone = CONFIG['zone_number']
        try:
            await self.bhyve.login()
        except Exception as e:
            errors.log_error("water_for_duration.login", str(e), exc_info=True)
            print(f"  ERROR: B-hyve login before watering failed: {e}")
            return

        minutes = max(secs / 60, 1 / 60)
        try:
            await self.bhyve.start_zone(minutes)
            msg = f"Zone {zone} watering started ({secs}s)"
            print(f"  {msg}")
            errors.log_error("watering", msg)
        except Exception as e:
            errors.log_error("water_for_duration.start_zone", str(e), exc_info=True)
            print(f"  ERROR: Starting zone {zone} failed: {e}")
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
        if self.blink.urls is None:
            if state.reauth_in_progress:
                print("  Re-auth already in progress, skipping")
                return
            try:
                await self.blink.start()
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

        try:
            camera = self.blink.cameras.get(CONFIG["camera_name"])
            if camera is None:
                names = list(self.blink.cameras.keys())
                msg = f"Camera '{CONFIG['camera_name']}' not found. Available: {names}"
                print(msg)
                errors.log_error("check_motion.camera", msg)
                return
        except Exception as e:
            errors.log_error("check_motion.camera", str(e), exc_info=True)
            print(f"  ERROR: Accessing camera failed: {e}")
            return

        try:
            record = camera.last_record
        except Exception as e:
            errors.log_error("check_motion.last_record", str(e), exc_info=True)
            print(f"  ERROR: Reading last_record failed: {e}")
            return

        if not record:
            return

        if record != self.last_record:
            self.last_record = record
            try:
                save_last_motion(record)
            except Exception as e:
                errors.log_error("check_motion.save_record", str(e), exc_info=True)

            ts = datetime.now().time().isoformat(timespec="seconds")
            msg = f"[{ts}] Motion detected on {CONFIG['camera_name']}"
            print(msg)
            errors.log_error("motion", msg)

            try:
                await self.water_for_duration()
            except Exception as e:
                errors.log_error("check_motion.water", str(e), exc_info=True)
                print(f"  ERROR: Watering failed: {e}")

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
    delattr(auth, "_oauth_csrf_token")
    delattr(auth, "_oauth_code_verifier")
    try:
        blink.setup_urls()
        await blink.get_homescreen()
        await blink.setup_post_verify()
    except Exception as e:
        errors.log_error("blink_2fa_key", f"Post-2FA setup failed: {e}", exc_info=True)
        print(f"  Post-2FA setup failed: {e}")
        return False
    return True


async def main():
    print("Starting Blink → B-hyve bridge")
    print(f"  Camera:     {CONFIG.get('camera_name', '?')}")
    print(f"  Zone:       {CONFIG.get('zone_number', '?')}")
    print(f"  Duration:   {DURATION_SECONDS}s")
    print(f"  Poll every: {POLL_INTERVAL}s")
    print(f"  Errors:     http://localhost:{os.environ.get('ERROR_PORT', 5000)}")

    try:
        async with aiohttp.ClientSession() as session:
            bhyve = BHyveClient(session)

            blink = Blink()
            try:
                blink.auth = Auth(
                    {
                        "username": CONFIG["blink_email"],
                        "password": CONFIG["blink_password"],
                    },
                    session=session,
                )
                await blink.start()
                state.active_blink = blink
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
