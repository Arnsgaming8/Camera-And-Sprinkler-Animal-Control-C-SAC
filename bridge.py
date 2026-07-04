import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp
import yaml

import errors
import state
from cameras import CameraProvider, CameraEvent, get_provider as get_camera_provider
from sprinklers import SprinklerProvider, get_provider as get_sprinkler_provider

# Import providers to trigger registration
import cameras.blink  # noqa: F401
import sprinklers.bhyve  # noqa: F401


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
POLL_INTERVAL = CONFIG.get("poll_interval_seconds", 30)
if not isinstance(POLL_INTERVAL, (int, float)) or POLL_INTERVAL < 1:
    POLL_INTERVAL = 30

# Shared status dict updated by main loop, read by server status endpoint
PROVIDER_STATUS: dict[str, dict] = {}

# Camera rules list, mutated in-place by server API handlers
CAMERAS: list[dict] = CONFIG.get("cameras", [])


async def _save_blink_auth(auth):
    """Compatibility: save Blink auth to config.yml and Render env var."""
    import json
    login_data = auth.login_attributes
    data = {k: login_data.get(k) for k in ("refresh_token", "hardware_id", "host", "region_id", "account_id", "user_id")}
    data = {k: v for k, v in data.items() if v is not None}
    if not data:
        return
    os.environ["BLINK_AUTH"] = json.dumps(data)
    try:
        with open(state.get_config_path()) as f:
            cfg = yaml.safe_load(f) or {}
        cfg["blink_auth"] = data
        with open(state.get_config_path(), "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
    except Exception as e:
        print(f"  Failed to save blink auth: {e}")
    api_key = os.environ.get("RENDER_API_KEY") or CONFIG.get("render_api_key")
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


def _load_blink_auth():
    """Compatibility: load saved Blink auth."""
    import json
    raw = os.environ.get("BLINK_AUTH")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    try:
        cfg = yaml.safe_load(open(state.get_config_path())) or {}
        return cfg.get("blink_auth", {})
    except Exception:
        return {}


def _get_credential(config: dict, *keys: str) -> str | None:
    for k in keys:
        val = config.get(k)
        if val:
            return str(val)
    return None


def _build_provider_config(config: dict, provider_name: str) -> dict:
    provider_configs = config.get("provider_configs", {})
    if provider_name in provider_configs:
        return provider_configs[provider_name]

    pconf: dict = {}
    if provider_name == "blink":
        pconf["email"] = _get_credential(config, "blink_email", "email")
        pconf["password"] = _get_credential(config, "blink_password", "password")
        pconf["motion_interval"] = config.get("motion_interval", 360)
        pconf["render_api_key"] = config.get("render_api_key")
    elif provider_name == "bhyve":
        pconf["email"] = _get_credential(config, "bhyve_email", "email")
        pconf["password"] = _get_credential(config, "bhyve_password", "password")
        pconf["device_id"] = _get_credential(config, "device_id")
    return pconf


def parse_rules(config: dict) -> list[dict]:
    rules: list[dict] = []
    camera_entries = config.get("cameras", [])

    if not camera_entries and config.get("camera_name"):
        camera_entries = [config]

    for entry in camera_entries:
        camera_provider = entry.get("provider", "blink")
        sprinkler_provider = entry.get("sprinkler", "bhyve")
        rule = {
            "camera_name": entry["name"],
            "camera_provider": camera_provider,
            "sprinkler_provider": sprinkler_provider,
            "zone": int(entry.get("zone", config.get("zone_number", 1))),
            "duration_seconds": int(entry.get("duration_seconds",
                                               config.get("duration_seconds",
                                                          config.get("duration_minutes", 5) * 60))),
            "arm": entry.get("arm", True),
            "no_water": entry.get("no_water", False),
        }
        rules.append(rule)
    return rules


def _deduplicate_providers(rules: list[dict]) -> dict[str, dict]:
    needed: dict[str, dict] = {}
    for r in rules:
        cp = r["camera_provider"]
        if cp not in needed:
            needed[cp] = _build_provider_config(CONFIG, cp)
        sp = r["sprinkler_provider"]
        if sp not in needed:
            needed[sp] = _build_provider_config(CONFIG, sp)
    return needed


async def handle_2fa_background(blink):
    state.blink_instance = blink
    state.twofa_pending = False
    try:
        while True:
            if getattr(blink, "urls", None) is not None:
                state.blink_instance = None
                break
            if not state.twofa_pending:
                await asyncio.sleep(1)
                continue
            pin = state.twofa_pin
            state.twofa_pin = None
            state.twofa_pending = False
            try:
                import json
                auth = blink.auth
                has_csrf = hasattr(auth, "_oauth_csrf_token")
                has_ver = hasattr(auth, "_oauth_code_verifier")
                if not has_csrf or not has_ver:
                    errors.log_error("blink_2fa_key", "OAuth state missing — click Resend")
                    continue

                from blinkpy import api as blink_api
                csrf = auth._oauth_csrf_token
                verifier = auth._oauth_code_verifier
                ok = await blink_api.oauth_verify_2fa(auth, csrf, pin)
                if not ok:
                    errors.log_error("blink_2fa_key", "Wrong/expired code")
                    continue

                code = await blink_api.oauth_get_authorization_code(auth)
                if not code:
                    continue

                token_data = await blink_api.oauth_exchange_code_for_token(auth, code, verifier, auth.hardware_id)
                if not token_data:
                    continue

                await auth._process_token_data(token_data)
                blink.setup_urls()
                for attempt in range(3):
                    try:
                        await blink.get_homescreen()
                        await blink.setup_post_verify()
                        break
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(3)
                        else:
                            raise

                state.blink_instance = None
                state.active_blink = blink
                await _save_blink_auth(auth)
                print("  2FA re-authentication successful")
                break
            except Exception as e:
                errors.log_error("check_motion.2fa", f"Re-auth exception: {e}", exc_info=True)
                state.blink_instance = blink
    finally:
        state.reauth_in_progress = False


async def main():
    errors.log_error("bridge.startup", "Bridge main() started")
    print("=== Motion → Sprinkler Bridge ===")
    rules = parse_rules(CONFIG)
    if not rules:
        print("No camera rules configured. Exiting.")
        return

    for r in rules:
        print(f"  {r['camera_provider']}:{r['camera_name']} → {r['sprinkler_provider']} zone {r['zone']} ({r['duration_seconds']}s)")
    print(f"  Poll every: {POLL_INTERVAL}s")

    provider_configs = _deduplicate_providers(rules)
    print(f"  Providers needed: {list(provider_configs.keys())}")

    async with aiohttp.ClientSession() as session:
        camera_instances: dict[str, CameraProvider] = {}
        sprinkler_instances: dict[str, SprinklerProvider] = {}
        last_watered: dict[str, float] = {}
        last_record: dict[str, str | None] = {}
        _providers_initialized = False
        _last_connect_attempt: dict[str, float] = {}
        _connect_retry_delay = 60

        errors.log_error("bridge.startup", "Entering main loop")
        print("  Entering main loop")

        while True:
            try:
                state.last_poll = datetime.now(timezone.utc).isoformat()

                if not _providers_initialized:
                    for pname, pconf in provider_configs.items():
                        if pname in camera_instances or pname in sprinkler_instances:
                            continue
                        try:
                            ptype = pconf.get("type", pname)
                            pclass = get_camera_provider(ptype)
                            inst = pclass(pconf, session=session)
                            camera_instances[pname] = inst
                            PROVIDER_STATUS[pname] = {"kind": "camera", "type": ptype, "connected": False}
                            print(f"  Camera provider '{pname}' ({ptype}) created")
                        except ValueError:
                            try:
                                ptype = pconf.get("type", pname)
                                pclass = get_sprinkler_provider(ptype)
                                inst = pclass(pconf, session=session)
                                sprinkler_instances[pname] = inst
                                PROVIDER_STATUS[pname] = {"kind": "sprinkler", "type": ptype, "connected": False}
                                print(f"  Sprinkler provider '{pname}' ({ptype}) created")
                            except ValueError:
                                print(f"  WARNING: Unknown provider '{pname}' (type '{pconf.get('type', '')}')")

                    _providers_initialized = True

                # Retry connecting providers that aren't connected yet
                for cam_name, cam_inst in camera_instances.items():
                    if getattr(cam_inst, "connected", False):
                        PROVIDER_STATUS.setdefault(cam_name, {})["connected"] = True
                        PROVIDER_STATUS.setdefault(cam_name, {}).pop("error", None)
                        continue
                    last_try = _last_connect_attempt.get(cam_name, 0.0)
                    if time.time() - last_try < _connect_retry_delay:
                        continue
                    _last_connect_attempt[cam_name] = time.time()
                    try:
                        ok = await asyncio.wait_for(cam_inst.connect(), timeout=30)
                        if ok:
                            PROVIDER_STATUS.setdefault(cam_name, {})["connected"] = True
                            PROVIDER_STATUS.setdefault(cam_name, {}).pop("error", None)
                            print(f"  {cam_name} connected")
                        elif state.blink_instance is not None:
                            print(f"  {cam_name}: 2FA pending")
                            asyncio.ensure_future(handle_2fa_background(state.blink_instance))
                    except asyncio.TimeoutError:
                        PROVIDER_STATUS.setdefault(cam_name, {})["error"] = "connect timed out"
                        errors.log_error("bridge", f"{cam_name} connect timed out")
                        print(f"  {cam_name}: connect timed out")
                    except Exception as e:
                        PROVIDER_STATUS.setdefault(cam_name, {})["error"] = str(e)[:120]
                        errors.log_error("bridge", f"{cam_name} connect error: {e}")
                        print(f"  {cam_name}: connect error: {e}")

                for sp_name, sp_inst in sprinkler_instances.items():
                    if sp_inst.connected:
                        PROVIDER_STATUS.setdefault(sp_name, {})["connected"] = True
                        PROVIDER_STATUS.setdefault(sp_name, {}).pop("error", None)
                        continue
                    last_try = _last_connect_attempt.get(sp_name, 0.0)
                    if time.time() - last_try < _connect_retry_delay:
                        continue
                    _last_connect_attempt[sp_name] = time.time()
                    try:
                        ok = await asyncio.wait_for(sp_inst.connect(), timeout=15)
                        if ok:
                            PROVIDER_STATUS.setdefault(sp_name, {})["connected"] = True
                            PROVIDER_STATUS.setdefault(sp_name, {}).pop("error", None)
                            print(f"  {sp_name} connected")
                    except asyncio.TimeoutError:
                        PROVIDER_STATUS.setdefault(sp_name, {})["error"] = "connect timed out"
                        print(f"  {sp_name}: connect timed out")
                    except Exception as e:
                        PROVIDER_STATUS.setdefault(sp_name, {})["error"] = str(e)[:120]
                        print(f"  {sp_name}: connect error: {e}")

                camera_events: list[tuple[str, CameraEvent]] = []
                for cp_name, cp_inst in camera_instances.items():
                    try:
                        events = await cp_inst.check_motion()
                        for ev in events:
                            camera_events.append((cp_name, ev))
                    except Exception as e:
                        errors.log_error(f"check_motion.{cp_name}", str(e), exc_info=True)
                        print(f"  ERROR in {cp_name}: {e}")

                motion_by_camera: dict[str, float] = {}
                for cp_name, ev in camera_events:
                    if ev.camera_name not in motion_by_camera or ev.timestamp > motion_by_camera[ev.camera_name]:
                        motion_by_camera[ev.camera_name] = ev.timestamp

                for rule in rules:
                    cname = rule["camera_name"]
                    zone = rule["zone"]
                    secs = rule["duration_seconds"]

                    if not rule["arm"]:
                        print(f"  Skipping '{cname}' — disarmed")
                        continue

                    if rule["no_water"]:
                        print(f"  Motion on '{cname}' — no_water enabled, skipping")
                        continue

                    last_w = last_watered.get(str(zone), 0.0)
                    cooldown = max(POLL_INTERVAL, secs + 5)
                    if time.time() - last_w < cooldown:
                        remaining = cooldown - (time.time() - last_w)
                        print(f"  Skipping '{cname}' — cooldown {remaining:.0f}s left for zone {zone}")
                        continue

                    motion_ts = motion_by_camera.get(cname)
                    if not motion_ts:
                        if cname not in last_record or last_record[cname] is None:
                            pass
                        continue

                    prev = last_record.get(cname)
                    if prev is not None and motion_ts <= float(prev):
                        continue

                    last_record[cname] = str(motion_ts)
                    last_watered[str(zone)] = time.time()

                    sp_name = rule["sprinkler_provider"]
                    sp_inst = sprinkler_instances.get(sp_name)
                    if not sp_inst:
                        errors.log_error("bridge", f"Sprinkler provider '{sp_name}' not found for zone {zone}")
                        continue

                    ts_str = datetime.now().strftime("%m/%d/%Y-%I:%M-%p")
                    msg = f"[{ts_str}] Motion on '{cname}' (prov:{rule['camera_provider']}) → zone {zone} ({secs}s)"
                    print(f"  {msg}")
                    errors.log_error("motion", msg)

                    try:
                        if not sp_inst.connected:
                            await sp_inst.connect()
                        ok = await sp_inst.start_zone(zone, secs)
                        if not ok:
                            errors.log_error("watering", f"Zone {zone} start failed")
                            continue
                        errors.log_error("watering", f"Zone {zone} watering started ({secs}s)")
                        await asyncio.sleep(secs)
                        await sp_inst.stop_zone()
                        errors.log_error("watering", f"Zone {zone} watering stopped")
                    except Exception as e:
                        errors.log_error("watering", f"Zone {zone} error: {e}", exc_info=True)
                        print(f"  ERROR watering zone {zone}: {e}")

            except Exception as e:
                errors.log_error("main_loop", str(e), exc_info=True)
                print(f"  ERROR in main loop: {e}")

            await asyncio.sleep(POLL_INTERVAL)


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
