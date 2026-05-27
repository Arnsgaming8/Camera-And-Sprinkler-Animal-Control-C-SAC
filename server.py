import asyncio
import json
import os
from datetime import datetime, timezone

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
    .toolbar { gap: 6px; }
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
    .water-form { flex-direction: row; flex-wrap: wrap; }
    .sidebar { width: 260px; left: -280px; padding: 16px; }
  }
  .water-form { display: flex; gap: 8px; align-items: center; margin-bottom: 16px;
                background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                padding: 12px 16px; flex-wrap: wrap; }
  .water-form label { color: #8b949e; font-size: 0.85rem; }
  .water-form input { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
                      padding: 6px 10px; color: #c9d1d9; font-size: 0.9rem; width: 70px; }
  .water-form input:focus { outline: none; border-color: #58a6ff; }
  .water-form select { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
                       padding: 6px 8px; color: #c9d1d9; font-size: 0.85rem; }
  .water-form button.go { background: #238636; border-color: #238636; color: #fff;
                          padding: 6px 20px; font-weight: 600; }
  .water-form button.go:hover { background: #2ea043; }
  .sidebar-btn { background: none; border: 1px solid #30363d; color: #c9d1d9;
                 font-size: 1.2rem; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
  .sidebar-btn:hover { background: #30363d; }
  .sidebar-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                     background: rgba(0,0,0,0.5); z-index: 98; display: none; }
  .sidebar-overlay.show { display: block; }
  .sidebar { position: fixed; top: 0; left: -320px; width: 300px; height: 100%;
             background: #161b22; border-right: 1px solid #30363d; z-index: 99;
             transition: left 0.25s; padding: 20px; overflow-y: auto; }
  .sidebar.open { left: 0; }
  .sidebar h2 { font-size: 1.1rem; margin-bottom: 16px; color: #c9d1d9; }
  .sidebar .close { float: right; background: none; border: none; color: #8b949e;
                    font-size: 1.4rem; cursor: pointer; padding: 0 4px; }
  .sidebar .close:hover { color: #f85149; }
  .sidebar .cam-item { display: flex; align-items: center; gap: 10px;
                       padding: 10px 0; border-bottom: 1px solid #21262d; }
  .sidebar .cam-name { flex: 1; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sidebar .cam-zone { color: #8b949e; font-size: 0.8rem; white-space: nowrap; }
  .sidebar .pencil { background: none; border: none; color: #8b949e; cursor: pointer;
                     font-size: 0.85rem; padding: 0 2px; flex-shrink: 0; }
  .sidebar .pencil:hover { color: #58a6ff; }
  .sidebar .add-btn { width: 100%; margin-top: 12px; text-align: center; }
  .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                   background: rgba(0,0,0,0.6); z-index: 100; display: none; }
  .modal-overlay.show { display: block; }
  .modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
           background: #161b22; border: 1px solid #30363d; border-radius: 10px;
           padding: 24px; z-index: 101; width: 320px; max-width: 90vw; display: none; }
  .modal.show { display: block; }
  .modal h3 { margin-bottom: 16px; }
  .modal label { display: block; color: #8b949e; font-size: 0.85rem; margin-bottom: 4px; margin-top: 12px; }
  .modal input { width: 100%; background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
                 padding: 8px 10px; color: #c9d1d9; font-size: 0.9rem; }
  .modal input:focus { outline: none; border-color: #58a6ff; }
  .modal .modal-actions { display: flex; gap: 8px; margin-top: 20px; }
  .modal .modal-actions button { flex: 1; }
  .modal .del-btn { background: #21262d; border-color: #da3633; color: #f85149; }
  .modal .del-btn:hover { background: #da3633; color: #fff; }
  .switch { position: relative; width: 40px; height: 22px; flex-shrink: 0; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .switch .slider { position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                    background: #30363d; border-radius: 22px; cursor: pointer; transition: 0.2s; }
  .switch .slider::before { content: ""; position: absolute; height: 16px; width: 16px;
                            left: 3px; bottom: 3px; background: #8b949e; border-radius: 50%;
                            transition: 0.2s; }
  .switch input:checked + .slider { background: #238636; }
  .switch input:checked + .slider::before { transform: translateX(18px); background: #fff; }
  .switch input:disabled + .slider { opacity: 0.4; cursor: not-allowed; }
</style>
</head>
<body>
<h1>Blink → B‑hyve Bridge</h1>
<p class="sub">Error &amp; event monitor</p>

<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
<div class="sidebar" id="sidebar">
  <button class="close" onclick="toggleSidebar()">&times;</button>
  <h2>Cameras</h2>
  <div id="camList"></div>
</div>

<div class="modal-overlay" id="modalOverlay" onclick="closeModal()"></div>
<div class="modal" id="modalBox">
  <h3 id="modalTitle">Edit Camera</h3>
  <form id="modalForm">
    <label for="modalName">Camera Name</label>
    <input type="text" id="modalName" required>
    <label for="modalZone">Zone</label>
    <input type="number" id="modalZone" min="1" max="12">
    <label for="modalDuration">Duration (seconds)</label>
    <input type="number" id="modalDuration" min="1">
    <div class="modal-actions">
      <button type="submit" class="primary">Save</button>
      <button type="button" onclick="closeModal()">Cancel</button>
      <button type="button" class="del-btn" id="modalDelete">Delete</button>
    </div>
  </form>
</div>

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
  <button class="sidebar-btn" onclick="toggleSidebar()">&#9776; Cameras</button>
  <span class="badge" id="count">0 errors</span>
  <span class="badge" id="pollStatus" style="font-size:0.8rem">poll: --</span>
  <button onclick="refresh()">Refresh</button>
  <span class="badge" id="zoneBadge" style="display:none"></span>
  <button class="danger" onclick="clearErrors()">Clear All</button>
</div>
<div class="water-form">
  <label>Zone</label>
  <input type="number" id="customZone" value="6" min="1" max="7" style="width:60px">
  <label>Duration</label>
  <input type="number" id="customDur" value="1" min="1" style="width:70px">
  <select id="customUnit">
    <option value="m">minutes</option>
    <option value="s">seconds</option>
  </select>
  <button class="go" onclick="customWater()">Go</button>
  <span id="customStatus" style="color:#8b949e;font-size:0.85rem"></span>
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
let pollCountdown = null;
async function pollStatus() {
  try {
    const r = await fetch("/api/status");
    const data = await r.json();
    const el = document.getElementById("pollStatus");
    if (data.last_poll && data.poll_interval) {
      const last = new Date(data.last_poll).getTime();
      const end = last + data.poll_interval * 1000;
      if (pollCountdown) clearInterval(pollCountdown);
      pollCountdown = setInterval(() => {
        const remaining = Math.max(0, Math.round((end - Date.now()) / 1000));
        el.textContent = remaining > 0 ? "poll in " + remaining + "s" : "poll now!";
      }, 500);
    } else {
      el.textContent = "poll: waiting...";
    }
  } catch(e) { /* ignore */ }
}
async function customWater() {
  const zone = document.getElementById("customZone").value;
  const dur = document.getElementById("customDur").value;
  const unit = document.getElementById("customUnit").value;
  const status = document.getElementById("customStatus");
  if (!zone || !dur) { status.textContent = "Enter zone and duration"; return; }
  status.textContent = "Starting...";
  try {
    const r = await fetch("/api/water/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({zone: parseInt(zone), duration: parseInt(dur), unit})
    });
    const data = await r.json();
    status.textContent = data.ok ? `Zone ${zone} started for ${dur}${unit}` : "Error: " + (data.error || "unknown");
    if (data.ok) setTimeout(() => status.textContent = "", 3000);
  } catch(e) { status.textContent = "Network error"; }
}
setInterval(refresh, 5000);
setInterval(check2FA, 5000);
setInterval(pollStatus, 5000);
setInterval(loadCameras, 5000);
refresh();
check2FA();
pollStatus();
loadCameras();

function toggleSidebar() {
  const s = document.getElementById("sidebar");
  const o = document.getElementById("sidebarOverlay");
  const open = s.classList.toggle("open");
  o.classList.toggle("show", open);
}
async const armPending = {};
function loadCameras() {
  try {
    const r = await fetch("/api/cameras");
    const data = await r.json();
    const el = document.getElementById("camList");
    el.innerHTML = (!data.connected
      ? '<div style="color:#8b949e;font-size:0.85rem;padding:8px 0">Blink not connected</div>'
      : ""
    ) + data.cameras.map(c => {
      const armed = c.name in armPending ? armPending[c.name] : c.armed;
      return `<div class="cam-item">
      <label class="switch">
        <input type="checkbox" ${armed ? "checked" : ""} ${data.connected ? "" : "disabled"}
               onchange="armCamera('${esc(c.name)}', this.checked, this)">
        <span class="slider"></span>
      </label>
      <span class="cam-name" title="Click to edit">${esc(c.name)}</span>
      <span class="cam-zone">zone ${c.zone} &middot; ${c.duration}s</span>
      <button class="pencil" onclick="openEditModal('${esc(c.name)}')" title="Edit camera">&#9998;</button>
    </div>`;
    }).join("") + '<button class="add-btn primary" onclick="openAddModal()">+ Add Camera</button>';
  } catch(e) { /* ignore */ }
}
async function armCamera(name, armed, checkbox) {
  armPending[name] = armed;
  checkbox.disabled = true;
  try {
    const r = await fetch("/api/camera/" + encodeURIComponent(name) + "/arm", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({armed})
    });
    if (!r.ok) checkbox.checked = !armed;
  } catch(e) { checkbox.checked = !armed; }
  delete armPending[name];
  checkbox.disabled = false;
}
async function openEditModal(name) {
  document.getElementById("modalTitle").textContent = "Edit Camera";
  document.getElementById("modalDelete").style.display = "";
  const r = await fetch("/api/cameras");
  const data = await r.json();
  const c = data.cameras.find(x => x.name === name);
  if (!c) return;
  document.getElementById("modalName").value = c.name;
  document.getElementById("modalZone").value = c.zone;
  document.getElementById("modalDuration").value = c.duration;
  document.getElementById("modalForm").onsubmit = (e) => {
    e.preventDefault();
    saveCamera(c.name);
  };
  document.getElementById("modalDelete").onclick = () => deleteCamera(c.name);
  openModal();
}
function openAddModal() {
  document.getElementById("modalTitle").textContent = "Add Camera";
  document.getElementById("modalDelete").style.display = "none";
  document.getElementById("modalName").value = "";
  document.getElementById("modalZone").value = 1;
  document.getElementById("modalDuration").value = 3;
  document.getElementById("modalForm").onsubmit = (e) => {
    e.preventDefault();
    saveCamera(null);
  };
  openModal();
}
function openModal() {
  document.getElementById("modalOverlay").classList.add("show");
  document.getElementById("modalBox").classList.add("show");
}
function closeModal() {
  document.getElementById("modalOverlay").classList.remove("show");
  document.getElementById("modalBox").classList.remove("show");
}
async function saveCamera(oldName) {
  const name = document.getElementById("modalName").value.trim();
  const zone = parseInt(document.getElementById("modalZone").value) || 1;
  const duration = parseInt(document.getElementById("modalDuration").value) || 3;
  if (!name) return;
  let url, method, body;
  if (oldName) {
    url = "/api/camera/" + encodeURIComponent(oldName);
    method = "PUT";
    body = {name, zone, duration};
  } else {
    url = "/api/cameras";
    method = "POST";
    body = {name, zone, duration};
  }
  const r = await fetch(url, {
    method,
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
  if (r.ok) {
    closeModal();
    loadCameras();
  }
}
async function deleteCamera(name) {
  if (!confirm('Remove camera "' + name + '"?')) return;
  const r = await fetch("/api/camera/" + encodeURIComponent(name), {method: "DELETE"});
  if (r.ok) {
    closeModal();
    loadCameras();
  }
}
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
    from bridge import POLL_INTERVAL
    return web.json_response({
        "status": "running",
        "error_count": len(errors.get_errors(9999)),
        "last_poll": state.last_poll,
        "poll_interval": POLL_INTERVAL,
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
            ok = await blink.start()
            if not ok:
                errors.log_error("main.blink_2fa_resend", "Blink login failed")
                return web.json_response({"ok": False, "error": "Blink login failed (check credentials)"}, status=500)
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


async def _manual_water(zone=None, duration_seconds=None):
    try:
        from bridge import CONFIG, DURATION_SECONDS, BHyveClient
        if zone is None:
            zone = CONFIG["zone_number"]
        if duration_seconds is None:
            duration_seconds = DURATION_SECONDS
        async with aiohttp.ClientSession() as session:
            bhyve = BHyveClient(session)
            bhyve.device_id = CONFIG["device_id"]
            await bhyve.login()
            minutes = max(1, round(duration_seconds / 60))
            await bhyve.start_zone(zone, minutes)
            errors.log_error("watering", f"Manual zone {zone} started ({duration_seconds}s)")
            await asyncio.sleep(duration_seconds)
            await bhyve.stop_zone()
            errors.log_error("watering", f"Manual zone {zone} stopped")
    except Exception as e:
        errors.log_error("manual_water", str(e), exc_info=True)


async def handle_config(request):
    from bridge import CONFIG, CAMERAS
    return web.json_response({
        "cameras": CAMERAS,
        "device_id": CONFIG.get("device_id", "?"),
    })


async def handle_water_start(request):
    try:
        body = await request.json()
        zone = body.get("zone")
        duration = body.get("duration")
        unit = body.get("unit", "m")
        if duration and unit == "s":
            duration_seconds = int(duration)
        elif duration:
            duration_seconds = int(duration) * 60
        else:
            zone = None
            duration_seconds = None
    except Exception:
        zone = None
        duration_seconds = None
    asyncio.ensure_future(_manual_water(zone, duration_seconds))
    from bridge import CONFIG
    return web.json_response({
        "ok": True,
        "zone": zone if zone else CONFIG.get("zone_number"),
    })


async def handle_esp32_trigger(request):
    try:
        body = await request.json()
        camera = body.get("camera", "ESP32")
        zone = int(body.get("zone", 1))
        duration = int(body.get("duration", 10))
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    ts = datetime.now(timezone.utc).time().isoformat(timespec="seconds")
    errors.log_error("motion", f"[{ts}] ESP32: {camera} → zone {zone} ({duration}s)")
    asyncio.ensure_future(_manual_water(zone, duration))
    return web.json_response({"ok": True, "zone": zone, "duration": duration})


def _cameras_json():
    from bridge import CAMERAS
    return json.dumps([{"name": c["name"], "zone": c["zone"],
                        "duration_seconds": c.get("duration_seconds", 3),
                        "arm": c.get("arm", True)} for c in CAMERAS])


async def _sync_cameras_config(event_label):
    import yaml
    from bridge import CAMERAS, CONFIG

    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        cfg["cameras"] = list(CAMERAS)
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
    except Exception as e:
        errors.log_error(f"{event_label}.save_yml", str(e), exc_info=True)

    api_key = os.environ.get("RENDER_API_KEY")
    if api_key:
        import aiohttp
        service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
        if not service_id:
            errors.log_error(f"{event_label}.render_api", "RENDER_SERVICE_ID not found")
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(
                    f"https://api.render.com/v1/services/{service_id}/env-vars",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"envVars": [{"key": "CAMERAS", "value": _cameras_json()}]},
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        errors.log_error(f"{event_label}.render_api", f"Render API {resp.status}: {text[:200]}")
                    else:
                        errors.log_error(event_label, "CAMERAS env var updated on Render")
        except Exception as e:
            errors.log_error(f"{event_label}.render_api", str(e), exc_info=True)

    errors.log_error(event_label, "Cameras config synced")


async def handle_cameras(request):
    from bridge import CAMERAS
    blink = state.active_blink
    connected = bool(blink and blink.cameras)
    result = []
    for cam in CAMERAS:
        name = cam["name"]
        armed = cam.get("arm", True)
        if connected:
            c = blink.cameras.get(name)
            if c is not None:
                armed = bool(getattr(c, "arm", armed))
        result.append({
            "name": name,
            "zone": cam["zone"],
            "duration": cam.get("duration_seconds", 3),
            "armed": armed,
        })
    return web.json_response({"connected": connected, "cameras": result})


async def handle_camera_arm(request):
    from bridge import CAMERAS
    name = request.match_info.get("name", "")
    try:
        body = await request.json()
        armed = bool(body.get("armed", False))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    blink = state.active_blink
    if not blink or not blink.cameras:
        return web.json_response({"ok": False, "error": "Blink not connected"}, status=503)
    camera = blink.cameras.get(name)
    if not camera:
        return web.json_response({"ok": False, "error": f"Camera '{name}' not found"}, status=404)
    await camera.async_arm(armed)
    for cam in CAMERAS:
        if cam["name"] == name:
            cam["arm"] = armed
            break
    errors.log_error("arming", f"{'Enabled' if armed else 'Disabled'} motion on '{name}'")
    return web.json_response({"ok": True, "name": name, "armed": armed})


async def handle_camera_zone(request):
    from bridge import CAMERAS
    name = request.match_info.get("name", "")
    try:
        body = await request.json()
        zone = int(body.get("zone", 0))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    if zone < 1 or zone > 12:
        return web.json_response({"ok": False, "error": "zone must be 1-12"}, status=400)

    for cam in CAMERAS:
        if cam["name"] == name:
            cam["zone"] = zone
            await _sync_cameras_config("camera_zone")
            return web.json_response({"ok": True, "name": name, "zone": zone})

    return web.json_response({"ok": False, "error": f"Camera '{name}' not found"}, status=404)


async def handle_camera_update(request):
    from bridge import CAMERAS
    name = request.match_info.get("name", "")
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)

    idx = next((i for i, c in enumerate(CAMERAS) if c["name"] == name), None)
    if idx is None:
        return web.json_response({"ok": False, "error": f"Camera '{name}' not found"}, status=404)

    CAMERAS[idx]["name"] = body.get("name", name)
    if body.get("zone") is not None:
        CAMERAS[idx]["zone"] = int(body["zone"])
    if body.get("duration") is not None:
        CAMERAS[idx]["duration_seconds"] = int(body["duration"])

    await _sync_cameras_config("camera_update")
    return web.json_response({"ok": True})


async def handle_camera_create(request):
    from bridge import CAMERAS
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        zone = int(body.get("zone", 1))
        duration = int(body.get("duration", 3))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    if not name:
        return web.json_response({"ok": False, "error": "name required"}, status=400)
    if any(c["name"] == name for c in CAMERAS):
        return web.json_response({"ok": False, "error": f"Camera '{name}' already exists"}, status=409)

    new_cam = {"name": name, "zone": zone, "duration_seconds": duration, "arm": True}
    CAMERAS.append(new_cam)
    await _sync_cameras_config("camera_create")
    return web.json_response({"ok": True, "camera": new_cam})


async def handle_camera_delete(request):
    from bridge import CAMERAS
    name = request.match_info.get("name", "")
    idx = next((i for i, c in enumerate(CAMERAS) if c["name"] == name), None)
    if idx is None:
        return web.json_response({"ok": False, "error": f"Camera '{name}' not found"}, status=404)

    CAMERAS.pop(idx)
    await _sync_cameras_config("camera_delete")
    return web.json_response({"ok": True})


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
    app.router.add_post("/api/esp32/trigger", handle_esp32_trigger)
    app.router.add_get("/api/cameras", handle_cameras)
    app.router.add_post("/api/cameras", handle_camera_create)
    app.router.add_put("/api/camera/{name}", handle_camera_update)
    app.router.add_delete("/api/camera/{name}", handle_camera_delete)
    app.router.add_post("/api/camera/{name}/arm", handle_camera_arm)
    app.router.add_post("/api/camera/{name}/zone", handle_camera_zone)
    return app


def main():
    app = create_app()
    print(f"Error dashboard at http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
