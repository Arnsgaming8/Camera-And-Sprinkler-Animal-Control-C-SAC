import os

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
  .entry.error { border-left: 4px solid #da3633; }
  .entry .head { display: flex; justify-content: space-between; align-items: center;
                 margin-bottom: 6px; font-size: 0.85rem; }
  .entry .source { font-weight: 600; color: #58a6ff; }
  .entry .time { color: #8b949e; font-size: 0.8rem; }
  .entry .msg { color: #c9d1d9; font-family: monospace; font-size: 0.85rem;
                white-space: pre-wrap; word-break: break-word; }
  .entry .trace-toggle { color: #8b949e; font-size: 0.8rem; cursor: pointer;
                         margin-top: 6px; display: inline-block; }
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
  <button onclick="refresh()">Refresh</button>
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
  container.innerHTML = errors.map(e => {
    const isMotion = e.source === "motion";
    const cls = isMotion ? "entry motion" : "entry error";
    const hasTrace = e.traceback && e.traceback !== "None";
    return `<div class="${cls}">
      <div class="head">
        <span class="source">${esc(e.source)}</span>
        <span class="time">${esc(e.timestamp)}</span>
      </div>
      <div class="msg">${esc(e.message)}</div>
      ${hasTrace ? `<span class="trace-toggle" onclick="this.nextElementSibling.classList.toggle('show')">Show traceback</span>
      <div class="trace">${esc(e.traceback)}</div>` : ""}
    </div>`;
  }).join("");
}
function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
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
        status.textContent = "2FA completed! Bridge is starting...";
        status.style.color = "#3fb950";
        document.getElementById("twofaBanner").classList.remove("show");
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
async function check2FA() {
  try {
    const r = await fetch("/api/blink/2fa/status");
    const data = await r.json();
    if (data.required) {
      document.getElementById("twofaBanner").classList.add("show");
    } else {
      document.getElementById("twofaBanner").classList.remove("show");
    }
  } catch(e) { /* ignore */ }
}
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
    return web.json_response({"status": "running", "error_count": len(errors.get_errors(9999))})


async def handle_2fa_status(request):
    return web.json_response({"required": state.blink_instance is not None and not state.twofa_event.is_set()})


async def handle_2fa_submit(request):
    try:
        data = await request.json()
        pin = data.get("pin", "").strip()
        if not pin:
            return web.json_response({"ok": False, "error": "Missing pin"}, status=400)
        if state.blink_instance is None:
            return web.json_response({"ok": False, "error": "No 2FA session active"}, status=400)
        state.twofa_pin = pin
        state.twofa_event.set()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_2fa_resend(request):
    blink = state.blink_instance
    if blink is None:
        return web.json_response({"ok": False, "error": "No 2FA session active"}, status=400)

    try:
        await blink.auth.startup()
    except BlinkTwoFARequiredError:
        errors.log_error("main.blink_2fa", "New 2FA code sent to email")
        return web.json_response({"ok": True, "message": "New code sent to your email"})
    except Exception as e:
        errors.log_error("main.blink_2fa_resend", str(e), exc_info=True)
        return web.json_response({"ok": False, "error": str(e)}, status=500)

    return web.json_response({"ok": False, "error": "Login succeeded unexpectedly"}, status=400)


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/errors", handle_errors)
    app.router.add_post("/api/clear", handle_clear)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/blink/2fa/status", handle_2fa_status)
    app.router.add_post("/api/blink/2fa", handle_2fa_submit)
    app.router.add_post("/api/blink/2fa/resend", handle_2fa_resend)
    return app


def main():
    app = create_app()
    print(f"Error dashboard at http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
