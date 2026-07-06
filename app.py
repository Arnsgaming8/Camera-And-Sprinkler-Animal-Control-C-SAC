import asyncio
import os

import aiohttp
import yaml

import state
CONFIG_PATH = state.get_config_path()

ENV_MAP = {
    "BLINK_EMAIL": "blink_email",
    "BLINK_PASSWORD": "blink_password",
    "CAMERA_NAME": "camera_name",
    "BHYVE_EMAIL": "bhyve_email",
    "BHYVE_PASSWORD": "bhyve_password",
    "DEVICE_ID": "device_id",
    "ZONE_NUMBER": "zone_number",
    "DURATION_SECONDS": "duration_seconds",
    "POLL_INTERVAL_SECONDS": "poll_interval_seconds",
    "RENDER_API_KEY": "render_api_key",
    "DISABLE_BLINK_POLLING": "disable_blink_polling",
}

REQUIRED = ["BLINK_EMAIL", "BLINK_PASSWORD", "BHYVE_EMAIL", "BHYVE_PASSWORD", "DEVICE_ID"]


def generate_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    blink_disabled = os.environ.get("DISABLE_BLINK_POLLING") == "1"
    required = [v for v in REQUIRED if not (blink_disabled and v.startswith("BLINK_"))]

    has_creds = all(os.environ.get(v) for v in required) or (
        config.get("bhyve_email") and config.get("bhyve_password") and config.get("device_id")
        and (blink_disabled or (config.get("blink_email") and config.get("blink_password")))
    )

    if not has_creds:
        print("Missing credentials. Starting in setup mode.")
        os.environ["SETUP_MODE"] = "1"

    for env_key, config_key in ENV_MAP.items():
        val = os.environ.get(env_key)
        if val is not None:
            if env_key in ("ZONE_NUMBER", "DURATION_SECONDS", "POLL_INTERVAL_SECONDS"):
                try:
                    val = int(val)
                except ValueError:
                    pass
            config[config_key] = val

    cameras_json = os.environ.get("CAMERAS")
    if cameras_json:
        import json
        try:
            env_cameras = json.loads(cameras_json)
            existing = {c["name"]: c for c in config.get("cameras", [])}
            merged = []
            env_names = {c["name"] for c in env_cameras}
            for c in env_cameras:
                if c["name"] in existing:
                    # Keep existing config (user may have changed via setup form)
                    merged.append(existing[c["name"]])
                else:
                    merged.append(c)
            for c in config.get("cameras", []):
                if c["name"] not in env_names:
                    merged.append(c)
            config["cameras"] = merged
        except json.JSONDecodeError as e:
            print(f"WARNING: CAMERAS env var is not valid JSON: {e}")

    for cam in config.get("cameras", []):
        cam.setdefault("no_water", False)
        cam.setdefault("arm", True)

    # Build provider_configs from flat env-var keys if not already set
    if "provider_configs" not in config:
        pconfs = {}
        if config.get("blink_email") and config.get("blink_password"):
            pconfs["blink"] = {
                "type": "blink",
                "email": config["blink_email"],
                "password": config["blink_password"],
                "motion_interval": config.get("motion_interval", 360),
            }
        if config.get("bhyve_email") and config.get("bhyve_password") and config.get("device_id"):
            pconfs["bhyve"] = {
                "type": "bhyve",
                "email": config["bhyve_email"],
                "password": config["bhyve_password"],
                "device_id": config["device_id"],
            }
        if pconfs:
            config["provider_configs"] = pconfs

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    print(f"Config written to {CONFIG_PATH}")

    for env_key, config_key in ENV_MAP.items():
        val = config.get(config_key)
        if val is not None:
            os.environ.setdefault(env_key, str(val))

    blink_auth_cfg = config.get("blink_auth")
    if blink_auth_cfg and not os.environ.get("BLINK_AUTH"):
        import json
        os.environ["BLINK_AUTH"] = json.dumps(blink_auth_cfg)


async def bridge_background_task(app):
    if os.environ.get("SETUP_MODE") == "1":
        print("Setup mode — bridge not started")
        return
    from bridge import main as bridge_main

    async def _run_bridge():
        try:
            await bridge_main()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            import errors as err_mod
            err_mod.log_error("app.bridge", str(exc), exc_info=True)
            print(f"Bridge exited: {exc}")

    app["bridge_task"] = asyncio.create_task(_run_bridge())

    # Keep Render free tier alive — ping every 14 min
    async def _keep_alive():
        url = os.environ.get("RENDER_EXTERNAL_URL")
        if not url:
            return
        while True:
            await asyncio.sleep(840)
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.get(url, timeout=10) as r:
                        print(f"  Keep-alive ping: {r.status}")
            except Exception as e:
                print(f"  Keep-alive ping failed: {e}")

    app["keep_alive_task"] = asyncio.create_task(_keep_alive())


async def cleanup_bridge(app):
    for key in ("bridge_task", "keep_alive_task"):
        task = app.get(key)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def main():
    print("=== Blink -> B-hyve Bridge ===")
    generate_config()
    os.environ.setdefault("ERRORS_MEMORY", "1")

    from aiohttp import web
    from server import create_app, HOST, PORT

    app = create_app()
    app.on_startup.append(bridge_background_task)
    app.on_cleanup.append(cleanup_bridge)

    ssl_ctx = None
    cert_path = os.path.join(os.path.dirname(CONFIG_PATH), "cert.pem")
    key_path = os.path.join(os.path.dirname(CONFIG_PATH), "key.pem")
    if os.path.exists(cert_path) and os.path.exists(key_path):
        import ssl
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(cert_path, key_path)
        print(f"Dashboard at https://0.0.0.0:{PORT}")
    else:
        print(f"Dashboard at http://0.0.0.0:{PORT}")
    web.run_app(app, host=HOST, port=PORT, ssl_context=ssl_ctx)


if __name__ == "__main__":
    main()
