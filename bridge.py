import asyncio
import os
import sys
from datetime import datetime, timezone

import aiohttp
import yaml
from blinkpy.blinkpy import Blink
from blinkpy.auth import Auth

import errors


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


class BHyveClient:
    def __init__(self, session):
        self.session = session
        self.token = None

    async def login(self):
        payload = {
            "email": CONFIG["bhyve_email"],
            "password": CONFIG["bhyve_password"],
            "device_id": "blink-bhyve-bridge",
            "app_version": "1.0",
            "manufacturer": "python",
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

    async def start_zone(self, minutes):
        zone = CONFIG["zone_number"]
        device = CONFIG["device_id"]
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with self.session.put(
                f"{BHYVE_API}/device/{device}/watering/zone/{zone}",
                json={"minutes": minutes},
                headers=headers,
            ) as r:
                data = await r.json()
                if r.status >= 400:
                    raise RuntimeError(
                        f"Start zone failed ({r.status}): {data.get('error', data)}"
                    )
                return r.status, data
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Start zone network error: {e}") from e

    async def stop_zone(self):
        zone = CONFIG["zone_number"]
        device = CONFIG["device_id"]
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with self.session.delete(
                f"{BHYVE_API}/device/{device}/watering/zone/{zone}", headers=headers
            ) as r:
                data = await r.json()
                if r.status >= 400:
                    raise RuntimeError(
                        f"Stop zone failed ({r.status}): {data.get('error', data)}"
                    )
                return r.status, data
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Stop zone network error: {e}") from e


class BlinkWatcher:
    def __init__(self, blink, bhyve):
        self.blink = blink
        self.bhyve = bhyve
        self.last_record = load_last_motion()

    async def water_for_duration(self):
        secs = DURATION_SECONDS
        try:
            await self.bhyve.login()
        except Exception as e:
            errors.log_error("water_for_duration.login", str(e), exc_info=True)
            print(f"  ERROR: B-hyve login before watering failed: {e}")
            return

        minutes = max(secs / 60, 1 / 60)
        try:
            status, data = await self.bhyve.start_zone(minutes)
            print(f"Zone {CONFIG['zone_number']} started. Status: {status}")
        except Exception as e:
            errors.log_error("water_for_duration.start_zone", str(e), exc_info=True)
            print(f"  ERROR: Starting zone failed: {e}")
            return

        print(f"Zone {CONFIG['zone_number']} watering for {secs}s...")
        try:
            await asyncio.sleep(secs)
        except asyncio.CancelledError:
            print("  Watering interrupted")
            errors.log_error("water_for_duration.sleep", "Watering sleep was cancelled")
        except Exception as e:
            errors.log_error("water_for_duration.sleep", f"Sleep error: {e}", exc_info=True)

        try:
            await self.bhyve.login()
            await self.bhyve.stop_zone()
            print(f"Zone {CONFIG['zone_number']} stopped")
        except Exception as e:
            errors.log_error("water_for_duration.stop_zone", str(e), exc_info=True)
            print(f"  ERROR: Stopping zone failed: {e}")

    async def check_motion(self):
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
