# BABBS — Brand-Agnostic Bridge System

<p align="left">
  <a href="https://render.com/deploy"><img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Render"></a>
</p>

A Python async bridge that detects motion on **any supported camera** and automatically waters **any supported sprinkler** zone. Runs entirely on **Render** (free tier) — no extra hardware needed.

## Supported Providers

### Camera Providers (15)

| Type | Python Package | Auth | Motion Detection |
|---|---|---|---|
| `blink` | blinkpy 0.25.5 | email + password + 2FA | Cloud event polling |
| `ring` | ring_doorbell | email + password | Cloud event polling |
| `reolink` | reolink-aio | host + username + password | Local API motion state |
| `hikvision` | hikvisionapi | host + username + password | ISAPI alert stream |
| `dahua` | dahua-rpc | host + username + password | Alarm records |
| `amcrest` | amcrest | host + username + password | Motion flag per channel |
| `foscam` | libpyfoscam | host + username + password | Alarm records |
| `unifi` | pyunifiprotect | host + username + password | Protect motion events |
| `axis` | axis | host + username + password | MQTT motion topics |
| `vivotek` | libpyvivotek | host + username + password | Motion detection param |
| `rtsp` | opencv-python | RTSP URL + auth | Background subtraction |
| `onvif` | onvif-zeep | host + username + password | Pull-point event subscription |
| `mjpeg` | opencv-python | MJPEG URL + auth | Background subtraction |
| `generic` | opencv-python | Stream URL + auth | Background subtraction |

### Sprinkler Providers (6)

| Type | Python Package | Auth |
|---|---|---|
| `bhyve` | aiohttp (custom) | email + password + device_id |
| `rachio` | RachioPy | API token |
| `rainbird` | pyrainbird | host + password (LNK module) |
| `hydrawise` | pydrawise | API key |
| `opensprinkler` | pyopensprinkler | host + password |
| `netro` | netrohomeapi | serial + API key |

## How it works

```
Camera provider ──(poll every Ns)──> Motion detected?
       │                    │               │ yes
       │                    │               ▼
       │                    │     Look up rule: camera → sprinkler zone
       │                    │               │
       │                    │               ▼
       │                    │     Sprinkler start_zone(duration)
       │                    │               │
       │                    │               ▼
       │                    │     Wait, then stop_zone()
       │                    │
  Dashboard UI (http://your-service.onrender.com)
```

Any camera provider can be paired with any sprinkler provider via rules.

## Files

| File | Purpose |
|---|---|
| `bridge.py` | Main daemon — polls cameras, triggers sprinklers with per-zone cooldown |
| `server.py` | Web dashboard — setup form, error log, sidebar, manual watering, 2FA |
| `cameras/__init__.py` | CameraProvider base class + registry |
| `cameras/*.py` | Individual camera provider implementations |
| `sprinklers/__init__.py` | SprinklerProvider base class + registry |
| `sprinklers/*.py` | Individual sprinkler provider implementations |
| `errors.py` | Shared error logging |
| `state.py` | Shared state — Blink instance, 2FA pin, poll timestamps |
| `app.py` | Render entry point — merges env vars into config, runs bridge + dashboard |
| `config.yml` | Local credentials and settings (gitignored) |
| `render.yaml` | Render Blueprint for one-click deployment |

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Click the Deploy to Render button
2. In "Specified configurations" click "Create all as new services" (ignore the credential fields)
3. After creation, go to Resources → click your web service
4. Once deployed, open the service URL → the setup form at `/setup` will prompt for credentials

## Config

Providers and rules are configured via `config.yml` or the setup form:

```yaml
provider_configs:
  blink:
    type: blink
    email: "user@example.com"
    password: "secret"
  bhyve:
    type: bhyve
    email: "user@example.com"
    password: "secret"
    device_id: "abc123"

poll_interval_seconds: 30

cameras:
  - name: "Front Door"
    provider: blink
    sprinkler: bhyve
    zone: 1
    duration_seconds: 20
  - name: "Back yard"
    provider: blink
    sprinkler: bhyve
    zone: 2
    duration_seconds: 30
```

## Local usage

```pwsh
pip install -r requirements.txt
python app.py
# Open http://localhost:5000 → /setup to configure
```

## Writing a new provider

Create a file in `cameras/` or `sprinklers/` that implements the base class and calls `register()`:

```python
from . import CameraProvider, CameraEvent, register

class MyCam(CameraProvider):
    name = "mybrand"
    async def connect(self) -> bool: ...
    async def check_motion(self) -> list[CameraEvent]: ...
    async def disconnect(self): ...

register("mybrand", MyCam)
```

Then add `import cameras.mybrand` to `bridge.py`.

## License

CC BY-NC-SA 4.0
