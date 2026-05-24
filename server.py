import asyncio
import os

import aiohttp
from aiohttp import web

import errors
import state

HOST = os.environ.get("ERROR_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("ERROR_PORT") or "5000")


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blink → B-hyve Bridge</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 24px; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .sub { color: #8b949e; font-size: 0.9rem; margin-bottom: 20px; }
  .toolbar { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
  .badge { background: #21262d; padding: 4px 12px; border-radius: 999px; font-size: 0.85rem; }
  .badge.err { background: #da3633; color: #fff; }
  .badge.warn { background: #d29922; color: #fff; }
  button { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
           padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
  button:hover { background: #30363d; }
  button.danger:hover { background: #da3633; border-color: #da3633; }
  button.primary { background: #238636; border-color: #238636; color: #fff; }
  button.primary:hover { background: #2ea043; }
  .empty { text-align: center; padding: 48px 0; color: #484f58; }
  .empty .icon { font-size: 2rem; margin-bottom: 8px; }
  .entry { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
           padding: 14px 16px; margin-bottom: 10px; }
  .entry.motion { border-left: 4px solid #d29922; }
  .entry.watering { border-left: 4px solid #3fb950; }
  .entry.error { border-left: 4px solid #da3633; }
  .entry .head { display: flex; justify-content: space-between; align-items: center;
                 margin-bottom: 6px; font-size: 0.85rem; }
  .entry .source { font-weight: 600; color: #58a6ff; }
  .entry .time { color: #8b949e; font-size: 0.8rem; }
  .entry .msg { color: #c9d1d9; font-family: monospace; font-size: 0.85rem;
                white-space: pre-wrap; word-break: break-word; }
  .entry .actions { display: flex; gap: 8px; align-items: center; margin-top: 6px; }
  .entry .copy-btn { color: #8b949e; font-size: 0.8rem; cursor: pointer; background: none;
                     border: 1px solid #30363d; border-radius: 4px; padding: 2px 8px; }
  .entry .copy-btn:hover { color: #58a6ff; border-color: #58a6ff; }
  .entry .copy-btn.copied { color: #3fb950; border-color: #3fb950; }
  .entry .trace-toggle { color: #8b949e; font-size: 0.8rem; cursor: pointer;
                         display: inline-block; }
  .entry .trace-toggle:hover { color: #58a6ff; }
  .entry .trace { display: none; margin-top: 6px; padding: 8px; background: #0d1117;
                  border-radius: 4px; font-family: monospace; font-size: 0.78rem;
                  color: #8b949e; white-space: pre-wrap; line-height: 1.4;
                  max-height: 300px; overflow: auto; }
  .entry .trace.show { display: block; }
  .twofa-banner { background: #1c2128; border: 1px solid #d29922; border-radius: 8px;
                  padding: 16px; margin-bottom: 16px; display: none; }
  .twofa-banner.show { display: block; }
  .twofa-banner h3 { color: #d29922; margin-bottom: 8px; }
  .twofa-banner p { color: #8b949e; font-size: 0.85rem; margin-bottom: 12px; }
  .twofa-form { display: flex; gap: 8px; align-items: center; }
  .twofa-form input { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
                      padding: 6px 12px; color: #c9d1d9; font-size: 1rem; width: 180px; }
  .twofa-form input:focus { outline: none; border-color: #58a6ff; }
  .twofa-status { margin-top: 8px; font-size: 0.85rem; color: #8b949e; }
  @media (max-width: 600px) {
    body { padding: 12px; }
    h1 { font-size: 1.2rem; }
    .toolbar button { flex: 1; text-align: center; }
    .twofa-form { flex-direction: column; align-items: stretch; }
    .twofa-form input { width: 100%; }
    .twofa-banner { padding: 12px; }
    .entry { padding: 10px 12px; }
    .entry .head { flex-direction: column; align-items: flex-start; gap: 2px; }
    .entry .actions { flex-wrap: wrap; }
    .entry .copy-btn { padding: 4px 12px; }
    .entry .trace { font-size: 0.72rem; max-height: 200px; }
    .entry .msg { font-size: 0.8rem; }
  }
</style>
</head>
<body>
<h1>Blink → B‑hyve Bridge</h1>
<p class="sub">Error &amp; event monitor</p>

<div class="twofa-banner" id="twofaBanner">
  <h3>&#9888; Two-Factor Authentication Required</h3>
  <p>A verification code has been sent to your Blink account email. Enter it below to complete sign-in.</p>
  <div class="twofa-form">
    <input type="text" id="twofaInput" placeholder="6-digit code" maxlength="6" autocomplete="off">
    <button class="primary" onclick="submit2FA()">Submit</button>
    <button onclick="resend2FA()">Resend Code</button>
  </div>
  <div class="twofa-status" id="twofaStatus"></div>
</div>

<div class="toolbar">
  <span class="badge" id="count">0 errors</span>
  <span class="badge" id="pollStatus" style="font-size:0.8rem">poll: --</span>
  <button onclick="refresh()">Refresh</button>
  <button onclick="waterZone()" id="waterBtn">Water Zone <span id="zoneNum">?</span></button>
  <span class="badge" id="zoneBadge" style="display:none"></span>
  <button class="danger" onclick="clearErrors()">Clear All</button>
</div>
<div id="entries"></div>

<script>
async function refresh() {
  const r = await fetch("/api/errors");
  const errors = await r.json();
  const container = document.getElementById("entries");
  document.getElementById("count").textContent = errors.length + " entries";
  document.getElementById("count").className = "badge" + (errors.length ? " err" : "");
  if (!errors.length) {
    container.innerHTML = '<div class="empty"><div class="icon">&#10003;</div>No errors recorded</div>';
    return;
  }
  container.innerHTML = errors.map((e, i) => {
    const isMotion = e.source === "motion";
    const isWatering = e.source === "watering";
    const cls = isMotion ? "entry motion" : isWatering ? "entry watering" : "entry error";
    const hasTrace = e.traceback && e.traceback !== "None";
    const enc = v => encodeURIComponent(JSON.stringify(v)).replace(/'/g, "%27");
    return `<div class="${cls}">
      <div class="head">
        <span class="source">${esc(e.source)}</span>
        <span class="time">${esc(e.timestamp)}</span>
      </div>
      <div class="msg">${esc(e.message)}</div>
      <div class="actions">
        <button class="copy-btn" onclick="copyError(this, '${enc(e)}')">Copy</button>
        ${hasTrace ? `<span class="trace-toggle" onclick="this.parentElement.nextElementSibling.classList.toggle('show')">Show traceback</span>` : ""}
      </div>
      ${hasTrace ? `<div class="trace">${esc(e.traceback)}<br><button class="copy-btn" style="margin-top:6px" onclick="copyError(this, '${enc({traceback: e.traceback})}')">Copy traceback</button></div>` : ""}
    </div>`;
  }).join("");
}
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
function copyError(btn, encoded) {
  const data = JSON.parse(decodeURIComponent(encoded));
  const text = [data.timestamp, data.source, data.message, data.traceback || ""].filter(Boolean).join("\n\n");
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
  }).catch(() => {
    btn.textContent = "Failed";
  });
}
async function clearErrors() {
  if (!confirm("Clear all error entries?")) return;
  await fetch("/api/clear", { method: "POST" });
  refresh();
}
async function submit2FA() {
  const pin = document.getElementById("twofaInput").value.trim();
  const status = document.getElementById("twofaStatus");
  if (!pin) { status.textContent = "Enter the code from your email."; return; }
  status.textContent = "Submitting...";
  try {
    const r = await fetch("/api/blink/2fa", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({pin})
    });
    const text = await r.text();
    if (text.startsWith("{")) {
      const data = JSON.parse(text);
      if (data.ok) {
        status.textContent = "Code submitted, verifying...";
        status.style.color = "#d29922";
        return;
      }
      status.textContent = "Error: " + (data.error || "unknown");
    } else {
      status.textContent = "Unexpected response: " + text.slice(0, 200);
    }
    status.style.color = "#da3633";
  } catch(e) {
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
    const text = await r.text();
    status.textContent = "Response: " + text.slice(0, 200);
    status.style.color = "#58a6ff";
  } catch(e) {
    status.textContent = "Network error: " + e.message;
    status.style.color = "#da3633";
  }
}
let prevRequired = null;
async function check2FA() {
  try {
    const r = await fetch("/api/blink/2fa/status");
    const data = await r.json();
    const banner = document.getElementById("twofaBanner");
    const status = document.getElementById("twofaStatus");
    if (data.required) {
      banner.classList.add("show");
      if (prevRequired === false) {
        status.textContent = "Code was incorrect or expired. Try again.";
        status.style.color = "#da3633";
      }
    } else if (prevRequired === true) {
      banner.classList.remove("show");
      status.textContent = "2FA completed! Bridge is running.";
      status.style.color = "#3fb950";
    }
    prevRequired = data.required;
  } catch(e) { /* ignore */ }
}
async function pollStatus() {
  try {
    const r = await fetch("/api/status");
    const data = await r.json();
    const el = document.getElementById("pollStatus");
    if (data.last_poll) {
      const t = new Date(data.last_poll).toLocaleTimeString();
      el.textContent = "poll: " + t;
    } else {
      el.textContent = "poll: waiting...";
    }
  } catch(e) { /* ignore */ }
}
async function waterZone() {
  const btn = document.getElementById("waterBtn");
  btn.disabled = true;
  btn.textContent = "Watering...";
  try {
    const r = await fetch("/api/water/start", { method: "POST" });
    const data = await r.json();
    if (data.ok) {
      btn.textContent = "Watering started!";
      setTimeout(() => { btn.textContent = "Water Zone " + (data.zone || "?"); btn.disabled = false; }, 2000);
    } else {
      btn.textContent = "Failed: " + (data.error || "unknown");
      setTimeout(() => { btn.textContent = "Water Zone " + (data.zone || "?"); btn.disabled = false; }, 3000);
    }
  } catch(e) {
    btn.textContent = "Network error";
    setTimeout(() => { btn.textContent = "Water Zone " + (data.zone || "?"); btn.disabled = false; }, 3000);
  }
}
async function loadConfig() {
  try {
    const r = await fetch("/api/config");
    const cfg = await r.json();
    document.getElementById("zoneNum").textContent = cfg.zone_number;
    const badge = document.getElementById("zoneBadge");
    badge.textContent = "Device: " + cfg.device_id.slice(0,8) + "…";
    badge.style.display = "";
  } catch(e) { /* ignore */ }
}
setInterval(refresh, 5000);
setInterval(check2FA, 5000);
setInterval(pollStatus, 5000);
refresh();
check2FA();
pollStatus();
loadConfig();
setInterval(refresh, 5000);
setInterval(check2FA, 5000);
refresh();
check2FA();
</script>
</body>
</html>"""


async def handle_index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def handle_errors(request):
    limit = int(request.query.get("limit", 50))
    return web.json_response(errors.get_errors(limit))


async def handle_clear(request):
    errors.clear_errors()
    return web.json_response({"ok": True})


async def handle_status(request):
    return web.json_response({
        "status": "running",
        "error_count": len(errors.get_errors(9999)),
        "last_poll": state.last_poll,
    })


async def handle_2fa_status(request):
    session_expired = (
        state.active_blink is not None
        and state.active_blink.urls is None
        and state.blink_instance is None
    )
    required = (
        (state.blink_instance is not None and not state.twofa_pending)
        or session_expired
    )
    return web.json_response({"required": required})


async def handle_2fa_submit(request):
    try:
        data = await request.json()
        pin = data.get("pin", "").strip()
        if not pin:
            return web.json_response({"ok": False, "error": "Missing pin"}, status=400)
        blink = state.blink_instance or state.active_blink
        if blink is None:
            return web.json_response({"ok": False, "error": "No 2FA session active"}, status=400)
        state.twofa_pin = pin
        state.twofa_pending = True
        if state.blink_instance is None:
            state.blink_instance = blink
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_2fa_resend(request):
    blink = state.blink_instance or state.active_blink
    if blink is None:
        return web.json_response({"ok": False, "error": "No 2FA session active"}, status=400)

    try:
        from blinkpy.auth import BlinkTwoFARequiredError
        from blinkpy.helpers.pkce import generate_pkce_pair

        try:
            await blink.start()
        except BlinkTwoFARequiredError:
            csrf = getattr(blink.auth, "_oauth_csrf_token", None)
            verifier = getattr(blink.auth, "_oauth_code_verifier", None)
            if not csrf or not verifier:
                code_verifier, code_challenge = generate_pkce_pair()
                blink.auth._oauth_code_verifier = code_verifier
                from blinkpy import api
                ok = await api.oauth_authorize_request(blink.auth, blink.auth.hardware_id, code_challenge)
                if not ok:
                    return web.json_response({"ok": False, "error": "OAuth authorize request failed"}, status=500)
                csrf = await api.oauth_get_signin_page(blink.auth)
                if not csrf:
                    return web.json_response({"ok": False, "error": "Failed to get CSRF token"}, status=500)
                email = blink.auth.data.get("username")
                password = blink.auth.data.get("password")
                result = await api.oauth_signin(blink.auth, email, password, csrf)
                if result != "2FA_REQUIRED":
                    return web.json_response({"ok": False, "error": f"Signin returned: {result}"}, status=500)
                blink.auth._oauth_csrf_token = csrf
            state.blink_instance = blink
            state.twofa_pending = False
            errors.log_error("main.blink_2fa", "New 2FA code sent to email")
            return web.json_response({"ok": True, "message": "New code sent to your email"})
        errors.log_error("main.blink_2fa_resend", "start() succeeded unexpectedly (no 2FA needed)")
        return web.json_response({"ok": False, "error": "Login succeeded (no 2FA needed)"}, status=400)
    except Exception as e:
        errors.log_error("main.blink_2fa_resend", str(e), exc_info=True)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def _manual_water():
    try:
        from bridge import CONFIG, DURATION_SECONDS, BHyveClient
        async with aiohttp.ClientSession() as session:
            bhyve = BHyveClient(session)
            bhyve.device_id = CONFIG["device_id"]
            bhyve.zone = CONFIG["zone_number"]
            await bhyve.login()
            minutes = max(1, round(DURATION_SECONDS / 60))
            await bhyve.start_zone(minutes)
            zone = CONFIG["zone_number"]
            errors.log_error("watering", f"Manual zone {zone} started ({DURATION_SECONDS}s)")
            await asyncio.sleep(DURATION_SECONDS)
            await bhyve.stop_zone()
            errors.log_error("watering", f"Manual zone {zone} stopped")
    except Exception as e:
        errors.log_error("manual_water", str(e), exc_info=True)


async def handle_config(request):
    from bridge import CONFIG
    return web.json_response({
        "zone_number": CONFIG.get("zone_number", "?"),
        "device_id": CONFIG.get("device_id", "?"),
        "duration_seconds": CONFIG.get("duration_seconds", "?"),
    })


async def handle_water_start(request):
    from bridge import CONFIG
    asyncio.ensure_future(_manual_water())
    return web.json_response({"ok": True, "zone": CONFIG.get("zone_number", "?")})


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/errors", handle_errors)
    app.router.add_post("/api/clear", handle_clear)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/blink/2fa/status", handle_2fa_status)
    app.router.add_post("/api/blink/2fa", handle_2fa_submit)
    app.router.add_post("/api/blink/2fa/resend", handle_2fa_resend)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/water/start", handle_water_start)
    return app


def main():
    app = create_app()
    print(f"Error dashboard at http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
