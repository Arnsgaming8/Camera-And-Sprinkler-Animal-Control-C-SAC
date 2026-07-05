import asyncio
import json
import os
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

import errors
import state

HOST = os.environ.get("ERROR_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("ERROR_PORT") or "5000")


SETUP_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BABBS — Setup</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 24px; max-width: 640px; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin-bottom: 4px; }
  .sub { color: #8b949e; font-size: 0.9rem; margin-bottom: 24px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
  .card h2 { font-size: 1rem; color: #c9d1d9; margin-bottom: 12px; }
  .card .hint { color: #8b949e; font-size: 0.78rem; margin-top: 4px; }
  label { display: block; color: #8b949e; font-size: 0.85rem; margin-bottom: 4px; margin-top: 12px; }
  .card label:first-child { margin-top: 0; }
  input, select { width: 100%; background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
                  padding: 8px 10px; color: #c9d1d9; font-size: 0.9rem; }
  select { cursor: pointer; }
  input:focus, select:focus { outline: none; border-color: #58a6ff; }
  .pw-wrap { position: relative; }
  .pw-wrap input { padding-right: 36px; }
  .pw-toggle { position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
               background: none; border: none; color: #8b949e; cursor: pointer;
               font-size: 1.1rem; padding: 4px; line-height: 1; }
  .pw-toggle:hover { color: #c9d1d9; }
  button.primary { background: #238636; border-color: #238636; color: #fff; border: none;
                   padding: 10px 24px; border-radius: 6px; cursor: pointer; font-size: 0.9rem;
                   font-weight: 600; width: 100%; margin-top: 16px; }
  button.primary:hover { background: #2ea043; }
  button.secondary { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
                     padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
                     margin-top: 8px; }
  button.secondary:hover { background: #30363d; }
  button.danger { background: #21262d; color: #f85149; border: 1px solid #30363d;
                  padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem;
                  margin-top: 8px; }
  button.danger:hover { background: #da3633; border-color: #da3633; color: #fff; }
  .status { margin-top: 12px; font-size: 0.85rem; color: #3fb950; text-align: center; }
  .status.err { color: #da3633; }
  hr { border: none; border-top: 1px solid #21262d; margin: 20px 0; }
  .rule-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; }
  .rule-row select, .rule-row input { flex: 1; }
  .rule-row button { flex: 0 0 auto; }
  .provider-entry { border: 1px solid #30363d; border-radius: 6px; padding: 12px; margin-top: 8px; }
  .flex-row { display: flex; gap: 8px; align-items: end; }
  .flex-row > * { flex: 1; }
  .tag { display: inline-block; background: #21262d; padding: 2px 8px; border-radius: 4px;
         font-size: 0.78rem; color: #8b949e; margin-left: 6px; }
</style>
</head>
<body>
<h1>BABBS — Setup</h1>
<p class="sub">Configure your cameras and sprinklers.</p>

<div class="card" id="providerConfigs">
  <h2>Camera Providers <span class="tag" id="availCamProviders"></span></h2>
  <div id="cameraProviders"></div>
  <button class="secondary" onclick="addCameraProvider()">+ Add Camera Provider</button>

  <hr>

  <h2>Sprinkler Providers <span class="tag" id="availSprinklerProviders"></span></h2>
  <div id="sprinklerProviders"></div>
  <button class="secondary" onclick="addSprinklerProvider()">+ Add Sprinkler Provider</button>
</div>

<div class="card" id="rulesCard">
  <h2>Rules <span class="tag">camera → sprinkler zone</span></h2>
  <div id="rules"></div>
  <button class="secondary" onclick="addRule()">+ Add Rule</button>
</div>

<div class="card">
  <h2>Settings</h2>
  <label>Poll Interval (seconds)</label>
  <input type="number" id="pollInterval" value="30" min="5">
  <label>Render API Key</label>
  <div class="pw-wrap">
    <input type="password" id="renderApiKey" placeholder="rnd_...">
    <button class="pw-toggle" onclick="togglePw('renderApiKey',this)" type="button">Show</button>
  </div>
  <div class="hint">Required only to persist credentials as Render env vars (API key with env_var_write scope).</div>
</div>

<button class="primary" onclick="saveSetup()">Save &amp; Restart</button>
<div class="status" id="setupStatus"></div>

<script>
const AVAIL_CAM = [
  "blink", "ring", "arlo", "nest", "wyze", "eufy", "reolink",
  "hikvision", "dahua", "amcrest", "foscam", "logitech", "tplink",
  "unifi", "axis", "bosch", "panasonic", "samsung", "vivotek",
  "geeni", "canary", "simplisafe", "lorex", "swann", "zmodo",
  "rtsp", "onvif", "mjpeg", "generic"
];
const AVAIL_SPRINKLER = [
  "bhyve", "rachio", "rainbird", "hunter", "hydrawise",
  "netro", "blossom", "skydrop", "sprinklerware", "openSprinkler",
  "generic"
];

let camProviders = [];
let sprProviders = [];
let rules = [];

function togglePw(id, btn) {
  const inp = document.getElementById(id);
  inp.type = inp.type === "password" ? "text" : "password";
  btn.textContent = inp.type === "password" ? "Show" : "Hide";
}

function camLabel(t) {
  const m = {
    blink:"Blink", ring:"Ring", arlo:"Arlo", nest:"Nest", wyze:"Wyze",
    eufy:"Eufy", reolink:"Reolink", hikvision:"Hikvision", dahua:"Dahua",
    amcrest:"Amcrest", foscam:"Foscam", logitech:"Logitech", tplink:"TP-Link",
    unifi:"UniFi", axis:"Axis", bosch:"Bosch", panasonic:"Panasonic",
    samsung:"Samsung", vivotek:"Vivotek", geeni:"Geeni", canary:"Canary",
    simplisafe:"SimpliSafe", lorex:"Lorex", swann:"Swann", zmodo:"Zmodo",
    rtsp:"RTSP", onvif:"ONVIF", mjpeg:"MJPEG", generic:"Generic"
  };
  return m[t] || t;
}
function sprLabel(t) {
  const m = {
    bhyve:"B-hyve", rachio:"Rachio", rainbird:"RainBird", hunter:"Hunter",
    hydrawise:"Hydrawise", netro:"Netro", blossom:"Blossom", skydrop:"SkyDrop",
    sprinklerware:"Sprinklerware", openSprinkler:"OpenSprinkler", generic:"Generic"
  };
  return m[t] || t;
}

function camFields(t) {
  if (t === "blink") return [
    {key:"email", label:"Email", type:"email"},
    {key:"password", label:"Password", type:"password"},
    {key:"motion_interval", label:"Motion Interval (minutes)", type:"number", val:360}
  ];
  return [{key:"email", label:"Email", type:"email"},{key:"password", label:"Password", type:"password"}];
}

function sprFields(t) {
  if (t === "bhyve") return [
    {key:"email", label:"Email", type:"email"},
    {key:"password", label:"Password", type:"password"},
    {key:"device_id", label:"Device ID", type:"text"}
  ];
  return [{key:"email", label:"Email", type:"email"},{key:"password", label:"Password", type:"password"}];
}

function renderProviders() {
  const camDiv = document.getElementById("cameraProviders");
  camDiv.innerHTML = camProviders.map((p, i) => renderProvider(p, i, "cam")).join("");
  document.getElementById("availCamProviders").textContent = AVAIL_CAM.join(", ");

  const sprDiv = document.getElementById("sprinklerProviders");
  sprDiv.innerHTML = sprProviders.map((p, i) => renderProvider(p, i, "spr")).join("");
  document.getElementById("availSprinklerProviders").textContent = AVAIL_SPRINKLER.join(", ");

  const rulesDiv = document.getElementById("rules");
  rulesDiv.innerHTML = rules.map((r, i) => renderRule(r, i)).join("");
}

function renderProvider(p, idx, kind) {
  const avail = kind === "cam" ? AVAIL_CAM : AVAIL_SPRINKLER;
  const fields = kind === "cam" ? camFields(p.type) : sprFields(p.type);
  const label = kind === "cam" ? camLabel : sprLabel;
  const listId = kind + "_type_" + idx;
  const opts = avail.map(t => `<option value="${t}">${label(t)}</option>`).join("");
  const fhtml = fields.map(f => {
    const val = p.config[f.key] !== undefined ? p.config[f.key] : (f.val !== undefined ? f.val : "");
    const inp = f.type === "password"
      ? `<div class="pw-wrap"><input type="password" id="${kind}_${idx}_${f.key}" value="${val}" placeholder="${f.label}" onchange="updateProv(${idx},'${kind}','${f.key}',this.value)"><button class="pw-toggle" onclick="togglePw('${kind}_${idx}_${f.key}',this)" type="button">Show</button></div>`
      : `<input type="${f.type}" id="${kind}_${idx}_${f.key}" value="${val}" placeholder="${f.label}" onchange="updateProv(${idx},'${kind}','${f.key}',this.value)">`;
    return `<label>${f.label}</label>${inp}`;
  }).join("");
  return `<div class="provider-entry">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <input list="${listId}" value="${p.type}" placeholder="Search provider type…" onchange="changeProviderType(${idx},'${kind}',this.value)" style="flex:1">
      <datalist id="${listId}">${opts}</datalist>
      <button class="danger" onclick="removeProvider(${idx},'${kind}')" style="margin:0 0 0 6px;font-size:0.8rem">Remove</button>
    </div>
    ${fhtml}
  </div>`;
}

function renderRule(r, idx) {
  const camOpts = camProviders.map((p, i) =>
    `<option value="cam_${i}" ${r.camera_provider === `cam_${i}` ? "selected" : ""}>${camLabel(p.type)} #${i+1}</option>`
  ).join("");
  const sprOpts = sprProviders.map((p, i) =>
    `<option value="spr_${i}" ${r.sprinkler_provider === `spr_${i}` ? "selected" : ""}>${sprLabel(p.type)} #${i+1}</option>`
  ).join("");
  return `<div class="rule-row">
    <select onchange="updateRule(${idx},'camera_provider',this.value)">
      <option value="">— Camera —</option>${camOpts}
    </select>
    <span style="color:#8b949e">→</span>
    <select onchange="updateRule(${idx},'sprinkler_provider',this.value)">
      <option value="">— Sprinkler —</option>${sprOpts}
    </select>
    <span style="color:#8b949e">zone</span>
    <input type="number" value="${r.zone || 1}" min="1" style="width:60px" onchange="updateRule(${idx},'zone',parseInt(this.value)||1)">
    <span style="color:#8b949e">for</span>
    <input type="number" value="${r.duration_seconds || 60}" min="1" style="width:70px" onchange="updateRule(${idx},'duration_seconds',parseInt(this.value)||60)">
    <span style="color:#8b949e">s</span>
    <button class="danger" onclick="rules.splice(${idx},1);renderProviders()" style="margin:0;font-size:0.8rem">✕</button>
  </div>`;
}

function addCameraProvider() { camProviders.push({type:"blink",config:{}}); renderProviders(); }
function addSprinklerProvider() { sprProviders.push({type:"bhyve",config:{}}); renderProviders(); }
function addRule() { rules.push({camera_provider:"",sprinkler_provider:"",zone:1,duration_seconds:60}); renderProviders(); }

function removeProvider(idx, kind) {
  if (kind === "cam") camProviders.splice(idx, 1); else sprProviders.splice(idx, 1);
  renderProviders();
}
function updateProv(idx, kind, key, val) {
  const arr = kind === "cam" ? camProviders : sprProviders;
  if (idx >= 0 && idx < arr.length) arr[idx].config[key] = val;
}
function changeProviderType(idx, kind, newType) {
  const arr = kind === "cam" ? camProviders : sprProviders;
  if (idx >= 0 && idx < arr.length) { arr[idx].type = newType; arr[idx].config = {}; }
  renderProviders();
}
function updateRule(idx, key, val) { if (idx >= 0 && idx < rules.length) rules[idx][key] = val; }

async function saveSetup() {
  const btn = document.querySelector("button.primary");
  const status = document.getElementById("setupStatus");
  btn.disabled = true; btn.textContent = "Saving...";
  status.className = "status"; status.textContent = "";

  const provider_configs = {};
  camProviders.forEach((p, i) => { provider_configs[`cam_${i}`] = {type:p.type, ...p.config}; });
  sprProviders.forEach((p, i) => { provider_configs[`spr_${i}`] = {type:p.type, ...p.config}; });

  const cameras = rules.filter(r => r.camera_provider && r.sprinkler_provider).map((r, i) => ({
    name: `Camera ${i+1}`,
    provider: r.camera_provider,
    sprinkler: r.sprinkler_provider,
    zone: r.zone,
    duration_seconds: r.duration_seconds,
    arm: true,
    no_water: false
  }));

  try {
    const r = await fetch("/api/setup", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        provider_configs,
        cameras,
        poll_interval_seconds: parseInt(document.getElementById("pollInterval").value) || 30,
        render_api_key: document.getElementById("renderApiKey").value.trim()
      })
    });
    const data = await r.json();
    if (data.ok) {
      status.textContent = data.message || "Saved! Restarting...";
      status.className = "status";
      setTimeout(() => { fetch("/api/restart", {method:"POST"}); location.href = "/"; }, 2000);
    } else {
      status.textContent = "Error: " + (data.error || "unknown");
      status.className = "status err";
    }
  } catch(e) {
    status.textContent = "Network error: " + e.message;
    status.className = "status err";
  }
  btn.disabled = false;
  btn.textContent = "Save &amp; Restart";
}

// Init with default providers
addCameraProvider();
addSprinklerProvider();
addRule();
</script>
</body>
</html>"""

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
  #toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
           background: #238636; color: #fff; padding: 10px 24px; border-radius: 8px;
           font-size: 0.9rem; z-index: 9999; opacity: 0; transition: opacity 0.3s;
           pointer-events: none; white-space: nowrap;
           max-width: min(600px, calc(100vw - 32px)); }
  #toast.error { background: #da3633; }
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
  .entry .del-btn { background: none; border: none; color: #8b949e; cursor: pointer; font-size: 1rem; padding: 0 4px; }
  .entry .del-btn:hover { color: #f85149; }
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
  .shutdown { background: #da3633; color: #fff; border: none; border-radius: 6px; padding: 6px 14px; font-size: 0.8rem; cursor: pointer; vertical-align: middle; margin-left: 12px; font-weight: 600; }
  .shutdown:hover { background: #f85149; }
  .water-form button.cancel-water { background: #da3633; color: #fff; border: none; border-radius: 6px; padding: 4px 10px; font-size: 0.8rem; cursor: pointer; display: none; }
  .water-form button.cancel-water:hover { background: #f85149; }
  .sidebar-btn { background: none; border: 1px solid #30363d; color: #c9d1d9;
                 font-size: 1.2rem; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
  .sidebar-btn:hover { background: #30363d; }
  .sidebar-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                     background: rgba(0,0,0,0.5); z-index: 98; display: none; }
  .sidebar-overlay.show { display: block; }
  .sidebar { position: fixed; top: 0; left: -320px; width: 300px; height: 100%;
             background: #161b22; border-right: 1px solid #30363d; z-index: 99;
             transition: left 0.25s; padding: 20px; overflow-y: auto;
             display: flex; flex-direction: column; }
  .sidebar.open { left: 0; }
  .sidebar-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .sidebar h2 { font-size: 1.1rem; margin: 0; color: #c9d1d9; }
  .sidebar .close { background: none; border: none; color: #8b949e;
                    font-size: 1.4rem; cursor: pointer; padding: 0 4px; line-height: 1; }
  .sidebar .close:hover { color: #f85149; }
  .sidebar .cam-item { display: flex; align-items: center; gap: 10px;
                       padding: 10px 0; border-bottom: 1px solid #21262d; }
  .sidebar .cam-name { flex: 1; font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sidebar .cam-zone { color: #8b949e; font-size: 0.8rem; white-space: nowrap; }
  .sidebar .pencil { background: none; border: none; color: #8b949e; cursor: pointer;
                     font-size: 0.85rem; padding: 0 2px; flex-shrink: 0; }
  .sidebar .pencil:hover { color: #58a6ff; }
  .sidebar .add-btn { width: 100%; margin-top: 12px; text-align: center; }
  #camList { flex: 1; overflow-y: auto; }
  .sidebar .logout-btn { margin-top: auto; align-self: flex-start; background: #da3633; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
  .sidebar .logout-btn:hover { background: #f85149; }
  #logoutBox .modal-actions button { flex: initial; }
  #logoutBox .modal-actions button.danger { background: #da3633; border-color: #da3633; color: #fff; }
  #logoutBox .modal-actions button.danger:hover { background: #f85149; }
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
  .switch input:disabled + .slider { cursor: not-allowed; }
  .switch input:disabled + .slider::before { opacity: 0.5; }
  #camList.loading .switch { pointer-events: none; }
  #camList.loading .switch .slider { opacity: 0.6; }
  #camList.loading .switch .slider::after { content: ""; position: absolute; top: 50%; left: -18px;
    width: 10px; height: 10px; margin: -5px 0 0; border: 2px solid transparent;
    border-top-color: #58a6ff; border-radius: 50%; animation: spin 0.6s linear infinite; z-index: 1; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<h1>Blink → B‑hyve Bridge <button class="shutdown" onclick="shutdownServer()">Shutdown Server</button></h1>
<p class="sub">Error &amp; event monitor</p>

<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
<div class="sidebar" id="sidebar">
  <div class="sidebar-head">
    <h2>Cameras</h2>
    <button class="close" onclick="toggleSidebar()">&times;</button>
  </div>
  <div id="camList"></div>
  <button class="logout-btn" onclick="openLogout()">Log Out</button>
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
    <label style="display:flex;align-items:center;gap:8px;margin-top:12px;color:#f85149;font-size:0.85rem">
      <input type="checkbox" id="modalNoWater" style="width:auto">
      Do not start sprinklers
    </label>
    <div class="modal-actions">
      <button type="submit" class="primary">Save</button>
      <button type="button" onclick="closeModal()">Cancel</button>
      <button type="button" class="del-btn" id="modalDelete">Delete</button>
    </div>
  </form>
</div>

<div class="modal" id="logoutBox">
  <h3 style="display:flex;align-items:center;justify-content:space-between">
    Log Out
    <button id="foreverLogoutBtn" onclick="foreverLogout()" style="background:#8b0000;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-weight:600;font-size:0.75rem">Forever Logout</button>
  </h3>
  <div id="logoutStep1">
    <p style="color:#8b949e;font-size:0.85rem;margin-bottom:12px">Log out of which account?</p>
    <div class="modal-actions" style="flex-direction:column">
      <button class="primary" onclick="showReauth('blink')">Blink</button>
      <button class="primary" onclick="showReauth('bhyve')">B-hyve</button>
      <button class="danger" onclick="showReauth('both')">Both</button>
      <button onclick="closeLogout()">Cancel</button>
    </div>
  </div>
  <div id="logoutStep2" style="display:none">
    <p style="color:#8b949e;font-size:0.85rem;margin-bottom:12px">Enter new credentials before logging out</p>
    <input type="hidden" id="reauthAccount" value="blink">
    <div id="reauthBlinkFields">
      <p style="font-size:0.85rem;font-weight:600;color:#58a6ff;margin-bottom:4px">Blink</p>
      <input type="email" id="reauthBlinkEmail" placeholder="Blink email" style="width:100%;margin-bottom:6px">
      <input type="password" id="reauthBlinkPass" placeholder="Blink password" style="width:100%;margin-bottom:12px">
    </div>
    <div id="reauthBhyveFields">
      <p style="font-size:0.85rem;font-weight:600;color:#3fb950;margin-bottom:4px">B-hyve</p>
      <input type="email" id="reauthBhyveEmail" placeholder="B-hyve email" style="width:100%;margin-bottom:6px">
      <input type="password" id="reauthBhyvePass" placeholder="B-hyve password" style="width:100%;margin-bottom:12px">
    </div>
    <div class="modal-actions">
      <button class="primary" onclick="submitReauth()">Save &amp; Reconnect</button>
      <button onclick="closeLogout()">Cancel</button>
    </div>
  </div>
  <div id="logoutConfirm" style="display:none">
    <p style="color:#8b949e;font-size:0.85rem;margin-bottom:16px">Clear saved credentials and log out of both accounts? You'll need to re-enter credentials to reconnect.</p>
    <div class="modal-actions">
      <button class="danger" onclick="confirmForeverLogout()">Yes, Log Out Forever</button>
      <button onclick="cancelForeverLogout()">Cancel</button>
    </div>
  </div>
</div>

<div class="modal" id="qrBox">
  <h3>Device Pass</h3>
  <div style="text-align:center;padding:16px 0">
    <img id="qrImage" src="" alt="QR Code" style="width:220px;height:220px;border-radius:8px">
    <p id="qrUrl" style="color:#8b949e;font-size:0.85rem;word-break:break-all;margin-top:8px"></p>
  </div>
  <div class="modal-actions">
    <button class="primary" onclick="closeQr()">Done</button>
  </div>
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
  <span id="providerStatuses"></span>
  <span class="badge" id="pollStatus" style="font-size:0.8rem">poll: --</span>
  <button id="refreshBtn" onclick="manualRefresh()">Refresh</button>
  <span class="badge" id="zoneBadge" style="display:none"></span>
  <button class="danger" onclick="clearErrors()">Clear All</button>
  <button onclick="generatePass()" style="background:#1f6feb;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600">Generate Pass</button>
  <button id="setupBtn" onclick="location.href='/setup'" style="background:#6e7681;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600">Setup</button>
  <button onclick="openLogout()" class="danger" style="padding:6px 14px;font-size:0.8rem;font-weight:600">Log Out</button>
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
  <button class="cancel-water" id="cancelWaterBtn" onclick="cancelWater()">Cancel</button>
  <span id="customStatus" style="color:#8b949e;font-size:0.85rem"></span>
</div>
<div id="entries"></div>
<div id="toast"></div>

<script>
async function manualRefresh() {
  const btn = document.getElementById("refreshBtn");
  btn.textContent = "Refreshed!";
  btn.disabled = true;
  await refresh();
  setTimeout(() => { btn.textContent = "Refresh"; btn.disabled = false; }, 2000);
}
async function refresh() {
  let r, errors;
  try {
    r = await fetch("/api/errors" + _nocache());
    errors = await r.json();
  } catch(e) { return; }
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
        <button class="del-btn" onclick="deleteError(${e.id})" title="Delete entry">&#128465;</button>
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
async function deleteError(id) {
  await fetch("/api/errors/delete", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id}) });
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
    const data = await r.json();
    if (data.ok) {
      status.textContent = "New code sent to your email";
      status.style.color = "#58a6ff";
    } else {
      status.textContent = JSON.stringify(data);
      status.style.color = "#da3633";
    }
  } catch(e) {
    status.textContent = "Network error: " + e.message;
    status.style.color = "#da3633";
  }
}
let prevRequired = null;
async function check2FA() {
  try {
    const r = await fetch("/api/blink/2fa/status" + _nocache());
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
    const r = await fetch("/api/status" + _nocache());
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
    const providerStatuses = document.getElementById("providerStatuses");
    if (data.providers) {
      providerStatuses.innerHTML = data.providers.map(p => {
        const label = p.type + ":" + p.key;
        const connected = p.connected;
        const err = p.error;
        const color = connected ? "#3fb950" : "#da3633";
        const text = connected ? (p.type + " connected") : (p.type + (err ? " err" : " disc."));
        return `<span class="badge" style="font-size:0.8rem;color:${color}" title="${label}${err ? ': '+err : ''}">${text}</span>`;
      }).join("");
    }
    const setupBtn = document.getElementById("setupBtn");
    const allOk = data.providers && data.providers.length > 0 && data.providers.every(p => p.connected);
    if (setupBtn) setupBtn.style.display = allOk ? "none" : "";
    const cancelBtn = document.getElementById("cancelWaterBtn");
    cancelBtn.style.display = data.water_active ? "inline-block" : "none";
  } catch(e) { /* ignore */ }
}
let waterStatusTimer = null;

async function cancelWater() {
  const status = document.getElementById("customStatus");
  const btn = document.getElementById("cancelWaterBtn");
  try {
    const r = await fetch("/api/water/stop", {method: "POST"});
    const data = await r.json();
    status.textContent = data.ok ? "Watering cancelled" : data.error || "unknown";
  } catch(e) { status.textContent = "Network error"; }
  btn.style.display = "none";
  if (waterStatusTimer) clearTimeout(waterStatusTimer);
  waterStatusTimer = setTimeout(() => status.textContent = "", 5000);
}

async function shutdownServer() {
  if (!confirm("Suspend the server on Render? You will need to manually start it from the Render dashboard.")) return;
  document.getElementById("customStatus").textContent = "Suspending server on Render...";
  clearInterval(pollInterval);
  clearInterval(check2FAInterval);
  clearInterval(pollStatusInterval);
  clearInterval(camerasInterval);
  if (pollCountdown) clearInterval(pollCountdown);
  document.querySelectorAll(".toolbar button").forEach(b => b.disabled = true);
  try {
    await fetch("/api/shutdown", {method: "POST"});
  } catch(e) { /* ok */ }
  document.getElementById("customStatus").textContent = "Server suspended. Reloading...";
  while (true) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const resp = await fetch("/api/errors");
      if (!resp.ok) { location.reload(); break; }
    } catch(e) { location.reload(); break; }
  }
}

async function customWater() {
  const zone = document.getElementById("customZone").value;
  const dur = document.getElementById("customDur").value;
  const unit = document.getElementById("customUnit").value;
  const status = document.getElementById("customStatus");
  const cancelBtn = document.getElementById("cancelWaterBtn");
  if (waterStatusTimer) clearTimeout(waterStatusTimer);
  if (!zone || !dur) {
    status.textContent = "Enter zone and duration";
    waterStatusTimer = setTimeout(() => status.textContent = "", 3000);
    return;
  }
  status.textContent = "Starting...";
  try {
    const r = await fetch("/api/water/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({zone: parseInt(zone), duration: parseInt(dur), unit})
    });
    const data = await r.json();
    if (data.cancelled) { status.textContent = "Cancelled"; return; }
    status.textContent = data.ok ? `Zone ${zone} started for ${dur}${unit}` : "Error: " + (data.error || "unknown");
    waterStatusTimer = setTimeout(() => { status.textContent = ""; }, (data.duration_seconds + 3) * 1000);
  } catch(e) { status.textContent = "Network error"; waterStatusTimer = setTimeout(() => { status.textContent = ""; }, 5000); }
}
var pollInterval = setInterval(refresh, 5000);
var check2FAInterval = setInterval(check2FA, 5000);
var pollStatusInterval = setInterval(pollStatus, 2000);
var camerasInterval = setInterval(loadCameras, 5000);
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
const armPending = {};
function _nocache() { return "?t=" + Date.now(); }
async function loadCameras() {
  const el = document.getElementById("camList");
  el.classList.add("loading");
  try {
    const r = await fetch("/api/cameras" + _nocache());
    const data = await r.json();
    const el = document.getElementById("camList");
    el.innerHTML = (!data.connected
      ? '<div style="color:#8b949e;font-size:0.85rem;padding:8px 0">Blink not connected</div>'
      : data.cameras.length === 0
        ? '<div style="color:#8b949e;font-size:0.85rem;padding:8px 0">No cameras configured</div>'
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
      <span class="cam-zone">${c.no_water ? '<span style="color:#f85149">No Watering</span>' : 'zone ' + c.zone + ' &middot; ' + c.duration + 's'}</span>
      <button class="pencil" onclick="openEditModal('${esc(c.name)}')" title="Edit camera">&#9998;</button>
    </div>`;
    }).join("") + '<button class="add-btn primary" onclick="openAddModal()">+ Add Camera</button>';
  } catch(e) { /* ignore */ }
  el.classList.remove("loading");
}
async function armCamera(name, armed, checkbox) {
  checkbox.disabled = true;
  armPending[name] = armed;
  checkbox.checked = armed;
  try {
    const r = await fetch("/api/camera/" + encodeURIComponent(name) + "/arm", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({armed})
    });
    if (r.ok) {
      showToast(armed ? "Motion enabled on " + name : "Motion disabled on " + name);
    } else {
      checkbox.checked = !armed;
      armPending[name] = !armed;
      showToast("Failed: " + (await r.json()).error, true);
    }
  } catch(e) {
    checkbox.checked = !armed;
    armPending[name] = !armed;
    showToast("Network error toggling motion", true);
  }
  delete armPending[name];
  checkbox.disabled = false;
}
function showToast(msg, isError) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = isError ? "error" : "";
  t.style.fontSize = "0.9rem";
  t.style.opacity = "1";
  while (t.scrollWidth > t.clientWidth && parseFloat(t.style.fontSize) > 0.45) {
    t.style.fontSize = (parseFloat(t.style.fontSize) - 0.05) + "rem";
  }
  if (window._toastTimer) clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { t.style.opacity = "0"; }, 3000);
}
async function openEditModal(name) {
  document.getElementById("modalTitle").textContent = "Edit Camera";
  document.getElementById("modalDelete").style.display = "";
  const r = await fetch("/api/cameras" + _nocache());
  const data = await r.json();
  const c = data.cameras.find(x => x.name === name);
  if (!c) return;
  document.getElementById("modalName").value = c.name;
  document.getElementById("modalZone").value = c.zone;
  document.getElementById("modalDuration").value = c.duration;
  document.getElementById("modalNoWater").checked = c.no_water;
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
  document.getElementById("modalNoWater").checked = false;
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
  document.getElementById("qrBox").classList.remove("show");
}
function openLogout() {
  document.getElementById("logoutStep1").style.display = "";
  document.getElementById("logoutStep2").style.display = "none";
  document.getElementById("reauthBlinkEmail").value = "";
  document.getElementById("reauthBlinkPass").value = "";
  document.getElementById("reauthBhyveEmail").value = "";
  document.getElementById("reauthBhyvePass").value = "";
  document.getElementById("foreverLogoutBtn").style.display = "";
  document.getElementById("modalOverlay").classList.add("show");
  document.getElementById("logoutBox").classList.add("show");
}
function closeLogout() {
  document.getElementById("modalOverlay").classList.remove("show");
  document.getElementById("logoutBox").classList.remove("show");
}
function showReauth(account) {
  document.getElementById("foreverLogoutBtn").style.display = "none";
  document.getElementById("reauthAccount").value = account;
  const showBlink = account === "blink" || account === "both";
  const showBhyve = account === "bhyve" || account === "both";
  document.getElementById("reauthBlinkFields").style.display = showBlink ? "" : "none";
  document.getElementById("reauthBhyveFields").style.display = showBhyve ? "" : "none";
  document.getElementById("reauthBlinkEmail").value = "";
  document.getElementById("reauthBlinkPass").value = "";
  document.getElementById("reauthBhyveEmail").value = "";
  document.getElementById("reauthBhyvePass").value = "";
  document.getElementById("logoutStep1").style.display = "none";
  document.getElementById("logoutStep2").style.display = "";
}
async function doLogout(accounts) {
  closeLogout();
  showToast("Logging out " + accounts.join(" + ") + "...");
  try {
    const r = await fetch("/api/logout", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({accounts})
    });
    const data = await r.json();
    if (!data.ok) { showToast("Logout failed: " + (data.error || "unknown"), true); return; }
    showToast("Logged out of " + accounts.join(" + "));
  } catch(e) { showToast("Network error logging out", true); }
}
async function submitReauth() {
  const accounts = document.getElementById("reauthAccount").value;
  const list = accounts === "both" ? ["blink", "bhyve"] : [accounts];
  const creds = {};
  let missing = [];
  for (const acct of list) {
    const emailEl = document.getElementById("reauth" + (acct === "blink" ? "Blink" : "Bhyve") + "Email");
    const passEl = document.getElementById("reauth" + (acct === "blink" ? "Blink" : "Bhyve") + "Pass");
    const email = emailEl.value.trim();
    const password = passEl.value;
    if (!email || !password) { missing.push(acct); continue; }
    creds[acct] = {email, password};
  }
  if (missing.length > 0) {
    const names = missing.map(a => a === "blink" ? "Blink" : "B-hyve");
    showToast("Fill in email and password for " + names.join(" and "), true);
    return;
  }
  closeLogout();
  showToast("Logging out and saving credentials...");
  try {
    const r = await fetch("/api/logout", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({accounts: list})
    });
    if (!r.ok) { showToast("Logout failed", true); return; }
    for (const acct of list) {
      await fetch("/api/reauth", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({account: acct, email: creds[acct].email, password: creds[acct].password})
      });
    }
    showToast("Credentials saved — bridge will reconnect");
  } catch(e) { showToast("Network error", true); }
}
function generatePass() {
  const url = window.location.origin;
  const qrUrl = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=" + encodeURIComponent(url);
  document.getElementById("qrImage").src = qrUrl;
  document.getElementById("qrUrl").textContent = url;
  document.getElementById("modalOverlay").classList.add("show");
  document.getElementById("qrBox").classList.add("show");
}
function closeQr() {
  document.getElementById("modalOverlay").classList.remove("show");
  document.getElementById("qrBox").classList.remove("show");
}
async function foreverLogout() {
  document.getElementById("logoutStep1").style.display = "none";
  document.getElementById("logoutStep2").style.display = "none";
  document.getElementById("logoutConfirm").style.display = "block";
}
async function confirmForeverLogout() {
  document.getElementById("logoutConfirm").style.display = "none";
  closeLogout();
  showToast("Logging out both accounts...");
  try {
    const r = await fetch("/api/logout", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({accounts: ["blink", "bhyve"]})
    });
    const data = await r.json();
    if (!data.ok) { showToast("Logout failed: " + (data.error || "unknown"), true); return; }
    await fetch("/api/logout/clear", {method: "POST"});
    showToast("Logged out of both accounts");
    if (confirm("Bridge logged out. Shut down the server on Render?")) {
      await fetch("/api/shutdown", {method: "POST"});
    } else {
      location.href = "/setup";
    }
  } catch(e) { showToast("Network error logging out", true); }
}
function cancelForeverLogout() {
  document.getElementById("logoutConfirm").style.display = "none";
  document.getElementById("logoutStep1").style.display = "block";
}
async function saveCamera(oldName) {
  const name = document.getElementById("modalName").value.trim();
  const zone = parseInt(document.getElementById("modalZone").value) || 1;
  const duration = parseInt(document.getElementById("modalDuration").value) || 3;
  const no_water = document.getElementById("modalNoWater").checked;
  if (!name) return;
  let url, method, body;
  if (oldName) {
    url = "/api/camera/" + encodeURIComponent(oldName);
    method = "PUT";
    body = {name, zone, duration, no_water};
  } else {
    url = "/api/cameras";
    method = "POST";
    body = {name, zone, duration, no_water};
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
    if request.query.get("setup") == "1" or os.environ.get("SETUP_MODE") == "1":
        return web.Response(text=SETUP_PAGE, content_type="text/html")

    if _has_credentials():
        return web.Response(text=PAGE, content_type="text/html")
    return web.Response(text=SETUP_PAGE, content_type="text/html")


def _has_credentials():
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    try:
        cfg = yaml.safe_load(open(config_path)) or {}
        return bool(cfg.get("bhyve_email") and cfg.get("bhyve_password") and cfg.get("device_id"))
    except Exception:
        return False


async def handle_setup_page(request):
    return web.Response(text=SETUP_PAGE, content_type="text/html")


async def handle_errors(request):
    limit = int(request.query.get("limit", 50))
    return web.json_response(errors.get_errors(limit))


async def handle_clear(request):
    errors.clear_errors()
    return web.json_response({"ok": True})


async def handle_error_delete(request):
    try:
        body = await request.json()
        entry_id = int(body.get("id"))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    ok = errors.delete_error(entry_id)
    return web.json_response({"ok": ok})


async def handle_status(request):
    from bridge import POLL_INTERVAL, CONFIG, PROVIDER_STATUS
    providers = []
    for key, p in PROVIDER_STATUS.items():
        providers.append({
            "key": key,
            "kind": p.get("kind", "?"),
            "type": p.get("type", "?"),
            "connected": p.get("connected", False),
            "error": p.get("error"),
        })
    return web.json_response({
        "status": "running",
        "error_count": len(errors.get_errors(9999)),
        "last_poll": state.last_poll,
        "poll_interval": POLL_INTERVAL,
        "water_active": _manual_water_task is not None and not _manual_water_task.done(),
        "providers": providers,
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
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    try:
        cfg = yaml.safe_load(open(config_path)) or {}
    except Exception:
        cfg = {}

    blink_email = cfg.get("blink_email") or os.environ.get("BLINK_EMAIL", "")
    blink_password = cfg.get("blink_password") or os.environ.get("BLINK_PASSWORD", "")
    if not blink_email or not blink_password:
        errors.log_error("main.blink_2fa_resend", "No Blink credentials configured")
        return web.json_response({"ok": False, "error": "No Blink credentials configured"}, status=400)

    try:
        from blinkpy.blinkpy import Blink
        from blinkpy.auth import Auth, BlinkTwoFARequiredError
        from bridge import _load_blink_auth

        async with aiohttp.ClientSession() as session:
            auth_data = {
                "username": blink_email,
                "password": blink_password,
            }
            auth_data.update(_load_blink_auth())
            blink_obj = Blink(motion_interval=360)
            blink_obj.auth = Auth(auth_data, session=session)

            try:
                ok = await blink_obj.start()
                if ok:
                    state.active_blink = blink_obj
                    state.blink_instance = None
                    state.twofa_pending = False
                    from bridge import _save_blink_auth
                    await _save_blink_auth(blink_obj.auth)
                    return web.json_response({"ok": True, "message": "Login successful."})
            except BlinkTwoFARequiredError:
                state.blink_instance = blink_obj
                state.twofa_pending = False
                errors.log_error("main.blink_2fa", "New 2FA code sent to email")
                return web.json_response({"ok": True, "message": "New code sent to your email"})
            except Exception as e:
                errors.log_error("main.blink_2fa_resend", f"Login failed: {e}")
                return web.json_response({"ok": False, "error": f"Blink login failed: {e}"}, status=500)

            errors.log_error("main.blink_2fa_resend", "Login succeeded unexpectedly (no 2FA)")
            state.active_blink = blink_obj
            state.blink_instance = None
            state.twofa_pending = False
            from bridge import _save_blink_auth
            await _save_blink_auth(blink_obj.auth)
            return web.json_response({"ok": True, "message": "Login successful."})
    except Exception as e:
        errors.log_error("main.blink_2fa_resend", str(e), exc_info=True)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


_manual_water_task = None
_water_pending = False
_water_cancel_requested = False


async def _get_sprinkler_provider(provider_key: str = "") -> "SprinklerProvider | None":
    from sprinklers import get_provider as get_sprinkler_cls
    from bridge import CONFIG as _cfg
    pconfs = _cfg.get("provider_configs", {})
    if provider_key and provider_key in pconfs:
        pconf = pconfs[provider_key]
    else:
        for k, v in pconfs.items():
            try:
                get_sprinkler_cls(v.get("type", ""))
                provider_key = k
                pconf = v
                break
            except ValueError:
                continue
        else:
            return None
    import aiohttp
    session = aiohttp.ClientSession()
    cls = get_sprinkler_cls(pconf.get("type", provider_key))
    inst = cls(pconf, session=session)
    try:
        ok = await asyncio.wait_for(inst.connect(), timeout=15)
        if not ok:
            await session.close()
            return None
    except Exception:
        await session.close()
        return None
    return inst


async def _manual_water(zone=None, duration_seconds=None):
    global _manual_water_task, _water_pending, _water_cancel_requested
    zone_started = False
    spr_inst = None
    try:
        if _water_cancel_requested:
            errors.log_error("watering", "Manual water aborted before start (cancel requested)")
            return
        spr_inst = await _get_sprinkler_provider()
        if not spr_inst:
            errors.log_error("watering", "No sprinkler provider available for manual water")
            return
        if zone is None:
            zone = 6
        if duration_seconds is None:
            duration_seconds = 60
        ok = await spr_inst.start_zone(zone, duration_seconds)
        if not ok:
            errors.log_error("watering", f"Manual zone {zone} start failed")
            return
        zone_started = True
        errors.log_error("watering", f"Manual zone {zone} started ({duration_seconds}s)")
        try:
            await asyncio.sleep(duration_seconds)
        except asyncio.CancelledError:
            pass
        try:
            await spr_inst.stop_zone()
        except Exception:
            pass
        errors.log_error("watering", f"Manual zone {zone} stopped")
    except asyncio.CancelledError:
        if zone_started and spr_inst:
            try:
                await spr_inst.stop_zone()
            except Exception:
                pass
    except Exception as e:
        errors.log_error("manual_water", str(e), exc_info=True)
    finally:
        if spr_inst:
            try:
                await spr_inst.disconnect()
                await spr_inst._session.close()
            except Exception:
                pass
        _manual_water_task = None
        _water_pending = False
        _water_cancel_requested = False


async def handle_config(request):
    from bridge import CONFIG, CAMERAS
    return web.json_response({
        "cameras": CAMERAS,
        "device_id": CONFIG.get("device_id", "?"),
    })


async def handle_water_start(request):
    global _manual_water_task, _water_pending, _water_cancel_requested
    _water_pending = True
    _water_cancel_requested = False
    try:
        body = await request.json()
        zone = body.get("zone")
        duration = body.get("duration")
        unit = body.get("unit", "m")
        if zone is None or zone < 1:
            _water_pending = False
            return web.json_response({"ok": False, "error": "zone must be >= 1"}, status=400)
        if duration is None or duration < 1:
            _water_pending = False
            return web.json_response({"ok": False, "error": "duration must be >= 1"}, status=400)
        zone = int(zone)
        duration_seconds = int(duration) * 60 if unit == "m" else int(duration)
    except Exception:
        _water_pending = False
        return web.json_response({"ok": False, "error": "bad request"}, status=400)

    if _water_cancel_requested:
        _water_pending = False
        _water_cancel_requested = False
        return web.json_response({"ok": True, "zone": zone, "cancelled": True})

    _manual_water_task = asyncio.ensure_future(_manual_water(zone, duration_seconds))
    return web.json_response({"ok": True, "zone": zone, "duration_seconds": duration_seconds})


async def handle_water_stop(request):
    global _manual_water_task, _water_pending, _water_cancel_requested
    if not _water_pending:
        return web.json_response({"ok": False, "error": "No active watering"}, status=400)
    _water_cancel_requested = True
    if _manual_water_task and not _manual_water_task.done():
        _manual_water_task.cancel()
    # Also try stopping via provider
    try:
        spr = await _get_sprinkler_provider()
        if spr:
            await spr.stop_zone()
            await spr.disconnect()
            await spr._session.close()
    except Exception:
        pass
    return web.json_response({"ok": True, "message": "Watering cancelled"})


async def handle_setup(request):
    import json, yaml
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)

    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    provider_configs = body.get("provider_configs")
    cameras = body.get("cameras")
    render_api_key = body.get("render_api_key", "").strip()
    poll_interval = body.get("poll_interval_seconds")

    # --- New format: provider_configs + cameras ---
    if provider_configs and cameras:
        cfg["provider_configs"] = provider_configs
        cfg["cameras"] = cameras
        if poll_interval:
            cfg["poll_interval_seconds"] = int(poll_interval)
        if render_api_key:
            cfg["render_api_key"] = render_api_key
    else:
        # --- Backward compatible: flat blink/bhyve fields ---
        blink_email = body.get("blink_email") or ""
        blink_password = body.get("blink_password") or ""
        bhyve_email = body.get("bhyve_email") or ""
        bhyve_password = body.get("bhyve_password") or ""
        device_id = body.get("device_id") or ""
        render_api_key = render_api_key or body.get("render_api_key") or ""

        if not bhyve_email or not bhyve_password or not device_id:
            return web.json_response({"ok": False, "error": "B-hyve email, password, and Device ID are required"}, status=400)

        cfg["bhyve_email"] = bhyve_email
        cfg["bhyve_password"] = bhyve_password
        cfg["device_id"] = device_id
        cfg["render_api_key"] = render_api_key

        if blink_email and blink_password:
            cfg["blink_email"] = blink_email
            cfg["blink_password"] = blink_password
            if "DISABLE_BLINK_POLLING" in os.environ:
                os.environ.pop("DISABLE_BLINK_POLLING", None)
            cfg.pop("disable_blink_polling", None)
        else:
            os.environ["DISABLE_BLINK_POLLING"] = "1"
            cfg["disable_blink_polling"] = True

        # Build provider_configs from flat fields
        cfg["provider_configs"] = {
            "blink": {"type": "blink", "email": blink_email, "password": blink_password},
            "bhyve": {"type": "bhyve", "email": bhyve_email, "password": bhyve_password, "device_id": device_id},
        }

        if not cfg.get("cameras"):
            cfg["cameras"] = [{"name": "Camera 1", "provider": "blink", "sprinkler": "bhyve",
                               "zone": 1, "duration_seconds": 60, "arm": False, "no_water": False}]

    # Write config
    try:
        with open(config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Failed to write config: {e}"}, status=500)
    os.environ.pop("SETUP_MODE", None)

    # --- Persist env vars to Render ---
    has_render_key = bool(os.environ.get("RENDER_API_KEY") or render_api_key)
    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")

    if has_render_key and service_id:
        if render_api_key:
            os.environ["RENDER_API_KEY"] = render_api_key
        api_key = render_api_key or os.environ.get("RENDER_API_KEY")
        try:
            async with aiohttp.ClientSession() as session:
                updates = {}
                # Flatten provider configs into env vars
                for pkey, pconf in provider_configs.items():
                    for k, v in pconf.items():
                        if k == "type":
                            continue
                        if v:
                            env_key = f"{pkey.upper()}_{k.upper()}"
                            updates[env_key] = str(v)
                if render_api_key:
                    updates["RENDER_API_KEY"] = render_api_key
                for env_key, val in updates.items():
                    async with session.put(
                        f"https://api.render.com/v1/services/{service_id}/env-vars/{env_key}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"key": env_key, "value": val},
                    ) as resp:
                        if resp.status not in (200, 201):
                            text = await resp.text()
                            errors.log_error("setup.render_api", f"Render API {resp.status} for {env_key}: {text[:200]}")
        except Exception as e:
            errors.log_error("setup.render_api", str(e), exc_info=True)
            return web.json_response({"ok": True, "message": "Saved to config.yml but failed to update Render env vars. Restart manually from Render dashboard."})

        from bridge import CAMERAS
        cfg_cameras = cfg.get("cameras", [])
        if cfg_cameras != list(CAMERAS):
            CAMERAS[:] = cfg_cameras
        await _sync_cameras_config("setup")

        return web.json_response({"ok": True, "message": "Credentials saved and synced to Render. Restarting service..."})

    return web.json_response({"ok": True, "message": "Saved to config.yml. Set RENDER_API_KEY env var for persistence, then restart from Render dashboard."})


async def handle_redeploy(request):
    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
    api_key = os.environ.get("RENDER_API_KEY")
    if not service_id or not api_key:
        return web.json_response({"ok": False, "error": "RENDER_API_KEY or RENDER_SERVICE_ID not set"}, status=400)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.render.com/v1/services/{service_id}/deploys",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"clearCache": "do_not_clear"},
            ) as resp:
                if resp.status == 201:
                    return web.json_response({"ok": True, "message": "Deploy triggered"})
                text = await resp.text()
                return web.json_response({"ok": False, "error": f"Render API {resp.status}: {text[:200]}"}, status=500)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_restart(request):
    global _manual_water_task, _water_pending
    if _manual_water_task and not _manual_water_task.done():
        _manual_water_task.cancel()
    try:
        spr = await _get_sprinkler_provider()
        if spr:
            await spr.stop_zone()
            await spr.disconnect()
            await spr._session.close()
    except Exception:
        pass
    _manual_water_task = None
    _water_pending = False
    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
    api_key = os.environ.get("RENDER_API_KEY")
    if service_id and api_key:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"https://api.render.com/v1/services/{service_id}/deploys",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"clearCache": "do_not_clear"},
                ) as resp:
                    if resp.status == 201:
                        return web.json_response({"ok": True, "message": "Restarting service on Render..."})
        except Exception:
            pass
    print("Restart: exiting process — Render will auto-restart")
    await asyncio.sleep(2)
    os._exit(0)


async def handle_shutdown(request):
    asyncio.ensure_future(_suspend_service())
    return web.json_response({"ok": True, "message": "Suspending service on Render..."})


async def _suspend_service():
    global _manual_water_task, _water_pending

    if _manual_water_task and not _manual_water_task.done():
        _manual_water_task.cancel()

    try:
        spr = await _get_sprinkler_provider()
        if spr:
            await spr.stop_zone()
            await spr.disconnect()
            await spr._session.close()
    except Exception:
        pass

    _manual_water_task = None
    _water_pending = False

    service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
    api_key = os.environ.get("RENDER_API_KEY")
    if not service_id or not api_key:
        print("Shutdown: Render API not configured — exiting process; Render will auto-restart")
        await asyncio.sleep(2)
        os._exit(0)
    try:
        async with aiohttp.ClientSession() as session2:
            async with session2.post(
                f"https://api.render.com/v1/services/{service_id}/suspend",
                headers={"Authorization": f"Bearer {api_key}"},
            ) as resp:
                if resp.status == 200:
                    errors.log_error("shutdown", "Service suspended on Render")
                else:
                    text = await resp.text()
                    errors.log_error("shutdown", f"Render suspend API {resp.status}: {text[:200]}")
    except Exception as e:
        errors.log_error("shutdown", str(e), exc_info=True)
    await asyncio.sleep(2)
    os._exit(0)


async def handle_esp32_trigger(request):
    try:
        body = await request.json()
        camera = body.get("camera", "ESP32")
        zone = int(body.get("zone", 1))
        duration = int(body.get("duration", 10))
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    ts = datetime.now(timezone.utc).time().isoformat(timespec="seconds")
    from bridge import CAMERAS
    no_water_zone = any(c.get("no_water", False) for c in CAMERAS if c.get("zone") == zone)
    if no_water_zone:
        errors.log_error("motion", f"[{ts}] ESP32: {camera} → zone {zone} — no_water enabled, skipped")
        return web.json_response({"ok": True, "skipped": True, "reason": "no_water enabled for this zone"})
    errors.log_error("motion", f"[{ts}] ESP32: {camera} → zone {zone} ({duration}s)")
    asyncio.ensure_future(_manual_water(zone, duration))
    return web.json_response({"ok": True, "zone": zone, "duration": duration})


def _cameras_json():
    from bridge import CAMERAS
    return json.dumps([{"name": c["name"], "zone": c["zone"],
                        "duration_seconds": c.get("duration_seconds", 3),
                        "arm": c.get("arm", True),
                        "no_water": c.get("no_water", False)} for c in CAMERAS])


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
    if not api_key:
        errors.log_error(f"{event_label}.warning", "RENDER_API_KEY not set — camera changes won't survive restart on Render")
    if api_key:
        import aiohttp
        service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
        if not service_id:
            errors.log_error(f"{event_label}.render_api", "RENDER_SERVICE_ID not found")
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"https://api.render.com/v1/services/{service_id}/env-vars/CAMERAS",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"key": "CAMERAS", "value": _cameras_json()},
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
    try:
        from bridge import CAMERAS
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": f"import bridge.CAMERAS failed: {e}"}, status=500)
    try:
        blink = state.active_blink
        connected = bool(blink and blink.cameras)
        result = []
        for cam in CAMERAS:
            name = cam["name"]
            armed = cam.get("arm", True)
            if connected and blink.cameras.get(name) is not None:
                blink_cam = blink.cameras[name]
                live = bool(getattr(blink_cam, "arm", True))
                last_user = state.last_user_arm.get(name, 0)
                if time.time() - last_user > 60:
                    armed = live
                else:
                    armed = cam.get("arm", True)
            result.append({
                "name": name,
                "zone": cam["zone"],
                "duration": cam.get("duration_seconds", 3),
                "armed": armed,
                "no_water": cam.get("no_water", False),
            })
        return web.json_response({"connected": connected, "cameras": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)


async def handle_camera_arm(request):
    from bridge import CAMERAS
    name = request.match_info.get("name", "")
    try:
        body = await request.json()
        armed = bool(body.get("armed", False))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    blink = state.active_blink
    if blink and blink.cameras:
        camera = blink.cameras.get(name)
        if camera:
            try:
                await camera.async_arm(armed)
            except Exception as exc:
                errors.log_error("arming", f"Blink sync failed for '{name}': {exc}")
        else:
            return web.json_response({"ok": False, "error": f"Camera '{name}' not found"}, status=404)
    for cam in CAMERAS:
        if cam["name"] == name:
            cam["arm"] = armed
            break
    state.last_user_arm[name] = time.time()
    asyncio.ensure_future(_sync_cameras_config("camera_arm"))
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
    if body.get("no_water") is not None:
        CAMERAS[idx]["no_water"] = bool(body["no_water"])

    await _sync_cameras_config("camera_update")
    return web.json_response({"ok": True})


async def handle_camera_create(request):
    from bridge import CAMERAS
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        zone = int(body.get("zone", 1))
        duration = int(body.get("duration", 3))
        no_water = bool(body.get("no_water", False))
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    if not name:
        return web.json_response({"ok": False, "error": "name required"}, status=400)
    if any(c["name"] == name for c in CAMERAS):
        return web.json_response({"ok": False, "error": f"Camera '{name}' already exists"}, status=409)

    new_arm = False
    blink = state.active_blink
    if blink and blink.cameras:
        blink_cam = blink.cameras.get(name)
        if blink_cam is None:
            for bn, bc in blink.cameras.items():
                if bn.lower() == name.lower():
                    blink_cam = bc
                    break
        if blink_cam is not None:
            new_arm = bool(getattr(blink_cam, "arm", True))
    new_cam = {"name": name, "zone": zone, "duration_seconds": duration, "arm": new_arm, "no_water": no_water}
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


async def handle_logout(request):
    import yaml
    try:
        body = await request.json()
        accounts = body.get("accounts", [])
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)

    config_path = os.path.join(os.path.dirname(__file__), "config.yml")

    if "blink" in accounts:
        state.active_blink = None
        state.twofa_pending = False
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
            cfg.pop("blink_auth", None)
            with open(config_path, "w") as f:
                yaml.dump(cfg, f)
        except Exception:
            pass
        if os.environ.get("BLINK_AUTH"):
            del os.environ["BLINK_AUTH"]
        errors.log_error("logout", "Blink logged out")

    if "bhyve" in accounts:
        try:
            from bridge import bhyve_client, BHYVE_WS
            if bhyve_client:
                await bhyve_client.disconnect()
        except Exception:
            pass
        errors.log_error("logout", "B-hyve logged out")

    return web.json_response({"ok": True})


async def handle_logout_clear(request):
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        for key in ["blink_email", "blink_password", "bhyve_email", "bhyve_password", "device_id", "blink_auth"]:
            cfg.pop(key, None)
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)
    except Exception:
        pass
    for key in ["BLINK_EMAIL", "BLINK_PASSWORD", "BHYVE_EMAIL", "BHYVE_PASSWORD", "DEVICE_ID", "BLINK_AUTH"]:
        os.environ.pop(key, None)
    return web.json_response({"ok": True, "message": "Credentials cleared. Restart to enter setup mode."})


async def handle_reauth(request):
    import yaml
    try:
        body = await request.json()
        account = body.get("account", "")
        email = body.get("email", "").strip()
        password = body.get("password", "")
    except Exception:
        return web.json_response({"ok": False, "error": "bad request"}, status=400)
    if not email or not password:
        return web.json_response({"ok": False, "error": "email and password required"}, status=400)

    config_path = os.path.join(os.path.dirname(__file__), "config.yml")
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}

    if account == "blink":
        cfg["blink_email"] = email
        cfg["blink_password"] = password
        cfg.pop("blink_auth", None)
        blink_key = "BLINK_EMAIL"
        blink_pass_key = "BLINK_PASSWORD"
    elif account == "bhyve":
        cfg["bhyve_email"] = email
        cfg["bhyve_password"] = password
        blink_key = "BHYVE_EMAIL"
        blink_pass_key = "BHYVE_PASSWORD"
    else:
        return web.json_response({"ok": False, "error": f"unknown account: {account}"}, status=400)

    try:
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"failed to save config: {e}"}, status=500)

    os.environ[blink_key] = email
    os.environ[blink_pass_key] = password

    api_key = os.environ.get("RENDER_API_KEY")
    if api_key:
        service_id = os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER_SERVICE")
        if service_id:
            import aiohttp
            updates = {blink_key: email, blink_pass_key: password}
            for key, val in updates.items():
                try:
                    async with aiohttp.ClientSession() as session:
                        await session.put(
                            f"https://api.render.com/v1/services/{service_id}/env-vars/{key}",
                            headers={"Authorization": f"Bearer {api_key}"},
                            json={"key": key, "value": val},
                        )
                except Exception:
                    pass

    errors.log_error("reauth", f"{account} credentials updated — reconnect on next retry")
    return web.json_response({"ok": True, "message": f"{account} credentials saved. Bridge will reconnect on next retry."})


@web.middleware
async def no_cache_middleware(request, handler):
    response = await handler(request)
    if isinstance(response, web.Response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

def create_app():
    app = web.Application(middlewares=[no_cache_middleware])
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/errors", handle_errors)
    app.router.add_post("/api/clear", handle_clear)
    app.router.add_post("/api/errors/delete", handle_error_delete)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/blink/2fa/status", handle_2fa_status)
    app.router.add_post("/api/blink/2fa", handle_2fa_submit)
    app.router.add_post("/api/blink/2fa/resend", handle_2fa_resend)
    app.router.add_get("/api/config", handle_config)
    app.router.add_post("/api/water/start", handle_water_start)
    app.router.add_post("/api/water/stop", handle_water_stop)
    app.router.add_post("/api/setup", handle_setup)
    app.router.add_post("/api/restart", handle_restart)
    app.router.add_post("/api/shutdown", handle_shutdown)
    app.router.add_post("/api/redeploy", handle_redeploy)
    app.router.add_post("/api/esp32/trigger", handle_esp32_trigger)
    app.router.add_get("/api/cameras", handle_cameras)
    app.router.add_post("/api/cameras", handle_camera_create)
    app.router.add_put("/api/camera/{name}", handle_camera_update)
    app.router.add_delete("/api/camera/{name}", handle_camera_delete)
    app.router.add_post("/api/camera/{name}/arm", handle_camera_arm)
    app.router.add_post("/api/camera/{name}/zone", handle_camera_zone)
    app.router.add_get("/setup", handle_setup_page)
    app.router.add_post("/api/logout", handle_logout)
    app.router.add_post("/api/logout/clear", handle_logout_clear)
    app.router.add_post("/api/reauth", handle_reauth)
    return app


def main():
    app = create_app()
    print(f"Error dashboard at http://localhost:{PORT}")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
