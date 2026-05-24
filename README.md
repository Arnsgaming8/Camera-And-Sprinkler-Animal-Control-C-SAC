# BABBS — Blink And Bhyve Bunny System

A Python async bridge that detects motion on a **Blink security camera** and automatically waters a sprinkler zone via the **Orbit B-hyve** API.

## How it works

```
Blink camera ──(poll every 30s)──> Motion detected?
                                         │ yes
                                         ▼
                                  B-hyve login()
                                         │
                                         ▼
                                  start_zone(20s)
                                         │
                                         ▼
                                  sleep(20s)
                                         │
                                         ▼
                                  stop_zone()
```

## Files

| File | Purpose |
|---|---|
| `bridge.py` | Main daemon — polls Blink, triggers B-hyve watering |
| `server.py` | Web dashboard showing all errors and motion events |
| `errors.py` | Shared error logging (file-based locally, in-memory on Render) |
| `app.py` | Combined entry point for Render (runs bridge + dashboard in one process) |
| `list_devices.py` | Utility to discover your B-hyve device ID and zones |
| `config.yml` | Local credentials and settings (not committed — generated from env vars in production) |
| `render.yaml` | Render Blueprint for one-click deployment |

## Local usage

```pwsh
pip install -r requirements.txt
```

1. Copy `config.example.yml` to `config.yml` and fill in your credentials.
2. Run `python list_devices.py` to find your B-hyve device ID and zone numbers.
3. Update `config.yml` with the device ID.

```pwsh
# Terminal 1 — start the bridge
python bridge.py

# Terminal 2 — start the error dashboard
python server.py
# Open http://localhost:5000
```

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Push this repo to GitHub.
2. Go to [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect this repo.
4. Fill in the secret environment variables (marked `sync: false` in `render.yaml`):

| Variable | Description |
|---|---|
| `BLINK_EMAIL` | Blink account email |
| `BLINK_PASSWORD` | Blink account password |
| `CAMERA_NAME` | Blink camera name (default: `Front Door`) |
| `BHYVE_EMAIL` | Orbit B-hyve account email |
| `BHYVE_PASSWORD` | Orbit B-hyve account password |
| `DEVICE_ID` | Your B-hyve sprinkler device ID |
| `ZONE_NUMBER` | Zone to water (default: `1`) |
| `DURATION_SECONDS` | Watering duration (default: `20`) |
| `POLL_INTERVAL_SECONDS` | How often to check Blink (default: `30`) |

The dashboard will be at `https://your-service.onrender.com`.

## Config

```yaml
blink_email: "your-blink-email@example.com"
blink_password: "your-blink-password"
camera_name: "Front Door"

bhyve_email: "your-bhyve-email@example.com"
bhyve_password: "your-bhyve-password"
device_id: "12345"
zone_number: 1
duration_seconds: 20
poll_interval_seconds: 30
```

## License

MIT
