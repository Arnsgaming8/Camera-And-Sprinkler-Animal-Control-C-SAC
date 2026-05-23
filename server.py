import os

from aiohttp import web

import errors

HOST = os.environ.get("ERROR_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("ERROR_PORT") or "5000")


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blink → B-hyve Bridge – Errors</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 24px; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .sub { color: #8b949e; font-size: 0.9rem; margin-bottom: 20px; }
  .toolbar { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; }
  .badge { background: #21262d; padding: 4px 12px; border-radius: 999px; font-size: 0.85rem; }
  .badge.err { background: #da3633; color: #fff; }
  button { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
           padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
  button:hover { background: #30363d; }
  button.danger:hover { background: #da3633; border-color: #da3633; }
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
</style>
</head>
<body>
<h1>Blink → B‑hyve Bridge</h1>
<p class="sub">Error &amp; event monitor</p>
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
setInterval(refresh, 5000);
refresh();
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


def create_app():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/errors", handle_errors)
    app.router.add_post("/api/clear", handle_clear)
    app.router.add_get("/api/status", handle_status)
    return app


def main():
    app = create_app()
    print(f"Error dashboard at http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
