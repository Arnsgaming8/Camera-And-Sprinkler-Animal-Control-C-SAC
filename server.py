import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

import aiohttp
import yaml
from aiohttp import web

import errors
import state

HOST = CONFIG.get("host", "0.0.0.0")
PORT = int(os.environ.get("PORT", os.environ.get("ERROR_PORT", 5000)))
try:
    CONFIG = yaml.safe_load(open(state.get_config_path())) or {}
except Exception:
    CONFIG = {}

SETUP_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BABBS Setup</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.container { width: 100%; max-width: 480px; padding: 24px; }
h1 { font-size: 1.5rem; margin-bottom: 8px; color: #f0f6fc; }
p { color: #8b949e; margin-bottom: 24px; font-size: 0.9rem; }
label { display: block; margin-top: 16px; margin-bottom: 4px; font-size: 0.85rem; color: #8b949e; }
input, select { width: 100%; padding: 10px 12px; background: #161b22; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; font-size: 0.9rem; }
input:focus { border-color: #58a6ff; outline: none; }
.hint { font-size: 0.8rem; color: #8b949e; margin-top: 4px; }
.hint a { color: #58a6ff; }
.btn { margin-top: 24px; padding: 10px 20px; background: #238636; border: none; border-radius: 6px; color: #fff; font-size: 0.9rem; cursor: pointer; width: 100%; }
.btn:hover { background: #2ea043; }
.status { margin-top: 12px; font-size: 0.85rem; color: #3fb950; text-align: center; }
.status.err { color: #da3633; }
</style>
</head>
<body>
<div class="container">
<h1>BABBS Setup</h1>
<p>Enter your credentials to get started.</p>
<form id="setupForm">
<label>Blink Email</label>
<input type="email" id="blink_email" value="ajusunaina@gmail.com" required>
<label>Blink Password</label>
<input type="password" id="blink_password" required>
<label>B-hyve Email</label>
<input type="email" id="bhyve_email" value="ajusunaina@gmail.com" required>
<label>B-hyve Password</label>
<input type="password" id="bhyve_password" required>
<label>Device ID</label>
<input type="text" id="device_id" placeholder="e.g. 607220244f0c161d5a0d1648" required>
<div class="hint">Run <code>list_devices.py</code> to find your device ID.</div>
<label>Zone Number</label>
<input type="number" id="zone_number" value="1" min="1">
<label>Duration (seconds)</label>
<input type="number" id="duration_seconds" value="180" min="1">
<label>Camera Name</label>
<input type="text" id="camera_name" placeholder="e.g. Back yard">
<label>Poll Interval (seconds)</label>
<input type="number" id="poll_interval_seconds" value="30" min="5">
<label>Render API Key (optional)</label>
<input type="password" id="render_api_key" placeholder="Leave blank for local-only">
<div class="hint">Required to save credentials as environment variables. Get it from <a href="https://dashboard.render.com" target="_blank" rel="noopener" style="color:#58a6ff">Render dashboard</a> &rarr; Account &rarr; API Keys &rarr; Create API Key (scope: env_var_write).</div>
<button type="submit" class="btn">Save &amp; Start</button>
</form>
<div class="status" id="setupStatus"></div>
</div>
<script>
document.getElementById("setupForm").onsubmit = async (e) => {
  e.preventDefault();
  const form = e.target;
  const data = {};
  for (const el of form.elements) if (el.id) data[el.id] = el.value;
  const status = document.getElementById("setupStatus");
  status.className = "status";
  status.textContent = "Saving...";
  try {
    const r = await fetch("/api/setup", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data) });
    const d = await r.json();
    if (d.ok) {
      status.textContent = d.message || "Saved! Restarting service...";
      status.className = "status";
      setTimeout(() => { fetch("/api/restart", {method: "POST"}); location.href = "/"; }, 2000);
    } else {
      status.textContent = "Error: " + (d.error || "unknown");
      status.className = "status err";
    }
  } catch (e) {
    status.textContent = "Network error: " + e.message;
    status.className = "status err";
  }
};
</script>
</body>
</html>"""

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BABBS</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #c9d1d9; display: flex; min-height: 100vh; }
.sidebar { width: 280px; background: #161b22; border-right: 1px solid #30363d; padding: 20px; display: flex; flex-direction: column; overflow-y: auto; }
.main { flex: 1; padding: 20px; overflow-y: auto; }
h1 { font-size: 1.3rem; color: #f0f6fc; margin-bottom: 16px; }
h2 { font-size: 1rem; color: #f0f6fc; margin-bottom: 8px; margin-top: 20px; }
.section { margin-bottom: 16px; }
label { display: block; font-size: 0.8rem; color: #8b949e; margin-bottom: 4px; margin-top: 8px; }
input, select, textarea { width: 100%; padding: 8px 10px; background: #0d1117; border: 1px solid #30363d; border-radius: 4px; color: #c9d1d9; font-size: 0.85rem; }
input:focus { border-color: #58a6ff; outline: none; }
textarea { font-family: monospace; font-size: 0.8rem; resize: vertical; min-height: 60px; }
.btn { padding: 6px 14px; background: #238636; border: none; border-radius: 4px; color: #fff; font-size: 0.8rem; cursor: pointer; display: inline-block; }
.btn:hover { background: #2ea043; }
.btn.danger { background: #da3633; }
.btn.danger:hover { background: #f85149; }
.btn.small { padding: 3px 10px; font-size: 0.75rem; }
.btn-group { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }
.status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75rem; font-weight: 600; }
.status-badge.green { background: #23863620; color: #3fb950; border: 1px solid #3fb950; }
.status-badge.red { background: #da363320; color: #f85149; border: 1px solid #f85149; }
.status-badge.yellow { background: #d2992220; color: #d29922; border: 1px solid #d29922; }
.camera-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #21262d; }
.camera-row:last-child { border-bottom: none; }
.camera-name { font-weight: 500; }
.camera-zone { color: #8b949e; font-size: 0.8rem; }
.camera-controls { display: flex; gap: 4px; align-items: center; }
.error-entry { padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 0.8rem; }
.error-entry:last-child { border-bottom: none; }
.error-time { color: #8b949e; font-size: 0.75rem; }
.error-source { color: #58a6ff; font-weight: 500; }
.error-msg { color: #c9d1d9; }
.error-del { cursor: pointer; color: #da3633; font-size: 0.75rem; margin-left: 8px; }
#errorList { max-height: 400px; overflow-y: auto; }
.water-active { color: #3fb950; font-weight: 600; }
.twofa-status { margin-top: 8px; font-size: 0.85rem; color: #8b949e; }
</style>
</head>
<body>
<div class="sidebar">
  <h1>BABBS</h1>
  <div class="section" id="statusSection">
    <div>Status: <span id="statusBadge" class="status-badge green">Running</span></div>
    <div style="margin-top:6px;font-size:0.8rem;color:#8b949e">Last poll: <span id="lastPoll">-</span></div>
    <div style="font-size:0.8rem;color:#8b949e">Errors: <span id="errorCount">0</span></div>
    <div style="font-size:0.8rem;color:#8b949e">Water: <span id="waterActive">No</span></div>
  </div>

  <div class="section">
    <h2>Cameras</h2>
    <div id="cameraList"></div>
  </div>

  <div class="section">
    <h2>2FA</h2>
    <input type="text" id="twofaInput" placeholder="Enter 6-digit code">
    <div class="btn-group">
      <button class="btn small" onclick="submit2FA()">Submit</button>
      <button class="btn small" onclick="resend2FA()">Resend Code</button>
    </div>
    <div class="twofa-status" id="twofaStatus"></div>
  </div>

  <div class="section">
    <h2>Manual Water</h2>
    <label>Zone</label>
    <input type="number" id="manualZone" value="1" min="1">
    <label>Duration (s)</label>
    <input type="number" id="manualDuration" value="60" min="1">
    <button class="btn" onclick="manualWater()">Water Now</button>
    <div style="margin-top:6px;font-size:0.8rem;color:#8b949e" id="manualStatus"></div>
  </div>

  <div class="section">
    <h2>Actions</h2>
    <div class="btn-group">
      <button class="btn small danger" onclick="clearErrors()">Clear Errors</button>
    </div>
  </div>
</div>

<div class="main">
  <h2>Error Log</h2>
  <div id="errorList"></div>
</div>

<script>
function _nocache() { return "?_=" + Date.now(); }

async function poll() {
  try {
    const r = await fetch("/api/status" + _nocache());
    const d = await r.json();
    const badge = document.getElementById("statusBadge");
    badge.textContent = d.status || "Unknown";
    badge.className = "status-badge " + (d.status === "running" ? "green" : "red");
    document.getElementById("lastPoll").textContent = d.last_poll ? new Date(d.last_poll).toLocaleString() : "-";
    document.getElementById("errorCount").textContent = d.error_count ?? "?";
    document.getElementById("waterActive").textContent = d.water_active ? "Yes" : "No";
    if (d.water_active) document.getElementById("waterActive").className = "water-active";
    else document.getElementById("waterActive").className = "";
  } catch (e) {
    document.getElementById("statusBadge").textContent = "Offline";
    document.getElementById("statusBadge").className = "status-badge red";
  }
}

async function loadCameras() {
  try {
    const r = await fetch("/api/cameras" + _nocache());
    const list = await r.json();
    const el = document.getElementById("cameraList");
    el.innerHTML = "";
    for (const c of list) {
      const row = document.createElement("div");
      row.className = "camera-row";
      row.innerHTML = `<span class="camera-name">${c.name}</span><span class="camera-zone">Zone ${c.zone}</span>
        <div class="camera-controls">
          <span class="status-badge ${c.arm ? 'green' : 'red'}">${c.arm ? 'Armed' : 'Disarmed'}</span>
          <button class="btn small" onclick="toggleArm('${c.name}', ${!c.arm})">Toggle</button>
        </div>`;
      el.appendChild(row);
    }
  } catch (e) {}
}

async function loadErrors() {
  try {
    const r = await fetch("/api/errors" + _nocache());
    const list = await r.json();
    const el = document.getElementById("errorList");
    el.innerHTML = "";
    if (list.length === 0) {
      el.innerHTML = '<div style="color:#8b949e;font-size:0.85rem">No errors logged.</div>';
      return;
    }
    for (const e of list) {
      const div = document.createElement("div");
      div.className = "error-entry";
      div.innerHTML = `<span class="error-time">${new Date(e.timestamp).toLocaleString()}</span>
        <span class="error-source">[${e.source}]</span>
        <span class="error-msg">${e.message}</span>
        <span class="error-del" onclick="deleteError(${e.id})">&#10005;</span>`;
      el.appendChild(div);
    }
  } catch (e) {}
}

async function toggleArm(name, arm) {
  try {
    await fetch("/api/cameras/arm", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name, arm}) });
    loadCameras();
  } catch (e) {}
}

async function submit2FA() {
  const pin = document.getElementById("twofaInput").value.trim();
  const status = document.getElementById("twofaStatus");
  if (!pin) { status.textContent = "Enter the code from your email."; return; }
  status.textContent = "Submitting...";
  try {
    const r = await fetch("/api/blink/2fa", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({pin}) });
    const d = await r.json();
    if (d.ok) {
      status.textContent = "Code submitted, verifying...";
      status.style.color = "#d29922";
    } else {
      status.textContent = "Error: " + (d.error || "unknown");
      status.style.color = "#da3633";
    }
  } catch (e) {
    status.textContent = "Network error: " + e.message;
    status.style.color = "#da3633";
  }
}

async function resend2FA() {
  const status = document.getElementById("twofaStatus");
  status.textContent = "Requesting new code...";
  status.style.color = "#8b949e";
  try {
    const r = await fetch("/api/blink/2fa/resend", { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      status.textContent = "New code sent to your email";
      status.style.color = "#58a6ff";
    } else {
      status.textContent = JSON.stringify(d);
      status.style.color = "#da3633";
    }
  } catch (e) {
    status.textContent = "Network error: " + e.message;
    status.style.color = "#da3633";
  }
}

async function manualWater() {
  const zone = parseInt(document.getElementById("manualZone").value);
  const duration = parseInt(document.getElementById("manualDuration").value);
  const status = document.getElementById("manualStatus");
  status.textContent = "Starting...";
  try {
    const r = await fetch("/api/water", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({zone, duration}) });
    const d = await r.json();
    status.textContent = d.message || "Done";
  } catch (e) {
    status.textContent = "Error: " + e.message;
  }
}

async function clearErrors() {
  await fetch("/api/clear", { method: "POST" });
  loadErrors();
}

async function deleteError(id) {
  await fetch("/api/errors/delete", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id}) });
  loadErrors();
}

poll(); loadCameras(); loadErrors();
setInterval(poll, 5000);
setInterval(loadErrors, 5000);
setInterval(loadCameras, 10000);
</script>
</body>
</html>"""


async def handle_index(request):
    if not CONFIG or not CONFIG.get("bhyve_email"):
        return web.Response(text=SETUP_PAGE, content_type="text/html")
    return web.Response(text=PAGE, content_type="text/html")


async def handle_setup(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    required = ["blink_email", "blink_password", "bhyve_email", "bhyve_password", "device_id"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        return web.json_response({"ok": False, "error": f"Missing: {missing}"}, status=400)

    cfg = {
        "bhyve_email": data["bhyve_email"],
        "bhyve_password": data["bhyve_password"],
        "blink_email": data["blink_email"],
        "blink_password": data["blink_password"],
        "device_id": data["device_id"],
        "zone_number": int(data.get("zone_number", 1)),
        "duration_seconds": int(data.get("duration_seconds", 180)),
        "poll_interval_seconds": int(data.get("poll_interval_seconds", 30)),
        "cameras": [],
    }
    camera_name = data.get("camera_name", "").strip()
    if camera_name:
        cfg["cameras"].append({
            "name": camera_name,
            "zone": cfg["zone_number"],
            "duration_seconds": cfg["duration_seconds"],
            "arm": True,
            "no_water": False,
        })
    if data.get("render_api_key"):
        cfg["render_api_key"] = data["render_api_key"]
        os.environ["RENDER_API_KEY"] = data["render_api_key"]
    try:
        with open(state.get_config_path(), "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        os.environ.pop("SETUP_MODE", None)
        return web.json_response({"ok": True, "message": "Saved to config.yml. Restart to apply."})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_status(request):
    error_list = errors.get_errors(1)
    error_count = len(errors.get_errors(999))
    active = getattr(state, "water_active", False)
    bc = state.active_blink is not None and state.active_blink.available
    bhyve_token = getattr(state, "bhyve_token", None)
    return web.json_response({
        "status": "running",
        "error_count": error_count,
        "last_poll": (state.last_poll.isoformat() if hasattr(state.last_poll, "isoformat") else state.last_poll) if state.last_poll else None,
        "poll_interval": 30,
        "water_active": active,
        "blink_connected": bc,
        "bhyve_connected": bhyve_token is not None,
    })


async def handle_errors(request):
    return web.json_response(errors.get_errors(50))


async def handle_clear(request):
    errors.clear_errors()
    return web.json_response({"ok": True})


async def handle_delete_error(request):
    try:
        data = await request.json()
        errors.delete_error(int(data["id"]))
    except Exception:
        pass
    return web.json_response({"ok": True})


async def handle_cameras(request):
    cameras = []
    for cam in CONFIG.get("cameras", []):
        cameras.append({
            "name": cam["name"],
            "zone": cam.get("zone", "?"),
            "arm": cam.get("arm", True),
        })
    return web.json_response(cameras)


async def handle_arm(request):
    try:
        data = await request.json()
        name = data["name"]
        arm = data["arm"]
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    try:
        with open(state.get_config_path()) as f:
            cfg = yaml.safe_load(f) or {}
        for cam in cfg.get("cameras", []):
            if cam["name"] == name:
                cam["arm"] = arm
                break
        with open(state.get_config_path(), "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_2fa(request):
    try:
        data = await request.json()
        pin = data.get("pin", "").strip()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    if not pin:
        return web.json_response({"ok": False, "error": "Pin is required"}, status=400)
    blink = state.blink_instance
    if blink is None:
        return web.json_response({"ok": False, "error": "No pending 2FA request"}, status=400)
    state.twofa_pin = pin
    state.twofa_pending = True
    return web.json_response({"ok": True})


async def handle_2fa_resend(request):
    blink = state.blink_instance
    if blink is None:
        return web.json_response({"ok": False, "error": "No active Blink session"}, status=400)
    try:
        new_blink = Blink(motion_interval=30)
        with open(state.get_config_path()) as f:
            cfg = yaml.safe_load(f) or {}
        auth_data = {
            "username": cfg["blink_email"],
            "password": cfg["blink_password"],
        }
        import json as _json
        raw = os.environ.get("BLINK_AUTH")
        if raw:
            try:
                auth_data.update(_json.loads(raw))
            except _json.JSONDecodeError:
                pass
        from blinkpy.auth import Auth
        async with aiohttp.ClientSession() as session:
            new_blink.auth = Auth(auth_data, session=session)
            try:
                await new_blink.start()
            except Exception:
                pass
            state.blink_instance = new_blink
            return web.json_response({"ok": True, "message": "New code sent. Check your email."})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_2fa_status(request):
    blink = state.blink_instance
    if blink is None:
        return web.json_response({"pending": False, "completed": True})
    try:
        if blink.urls is not None:
            state.blink_instance = None
            state.active_blink = blink
            return web.json_response({"ok": True, "pending": False, "completed": True})
    except Exception:
        pass
    return web.json_response({"pending": state.twofa_pending, "completed": False, "pin_set": state.twofa_pin is not None})


async def handle_water(request):
    try:
        data = await request.json()
        zone = int(data["zone"])
        duration = int(data.get("duration", 60))
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    blink = state.active_blink
    if blink is None:
        return web.json_response({"ok": False, "error": "Bridge not ready"}, status=400)
    from bridge import BHyveClient
    async with aiohttp.ClientSession() as session:
        bhyve = BHyveClient(session)
        try:
            await bhyve.login()
            state.bhyve_token = bhyve.token
            await bhyve.start_zone(zone, max(duration / 60, 1 / 60))
            state.water_active = True
            asyncio.ensure_future(_stop_after(bhyve, zone, duration))
            return web.json_response({"ok": True, "message": f"Zone {zone} watering for {duration}s"})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)


async def _stop_after(bhyve, zone, duration):
    await asyncio.sleep(duration)
    try:
        await bhyve.stop_zone()
    except Exception:
        pass
    state.water_active = False


async def handle_reauth(request):
    blink = state.active_blink
    if blink is None:
        return web.json_response({"ok": False, "error": "Bridge not ready"}, status=400)
    try:
        await blink.start()
        return web.json_response({"ok": True, "message": "Re-authenticated"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_post("/api/setup", handle_setup)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/errors", handle_errors)
    app.router.add_post("/api/clear", handle_clear)
    app.router.add_post("/api/errors/delete", handle_delete_error)
    app.router.add_get("/api/cameras", handle_cameras)
    app.router.add_post("/api/cameras/arm", handle_arm)
    app.router.add_post("/api/blink/2fa", handle_2fa)
    app.router.add_post("/api/blink/2fa/resend", handle_2fa_resend)
    app.router.add_get("/api/blink/2fa/status", handle_2fa_status)
    app.router.add_post("/api/water", handle_water)
    app.router.add_post("/api/reauth", handle_reauth)
    return app


async def _start_pinger(app, url):
    async def ping():
        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    await asyncio.sleep(300)
                    try:
                        await session.get(url, timeout=5)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
    app["ping_task"] = asyncio.create_task(ping())


def _maybe_start_pinger(app, url):
    if url:
        asyncio.ensure_future(_start_pinger(app, url))
