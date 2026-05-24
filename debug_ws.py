import asyncio
import json
import sys
from datetime import datetime, timezone

import aiohttp
import yaml

BHYVE_API = "https://api.orbitbhyve.com/v1"
BHYVE_WS = "wss://api.orbitbhyve.com/v1/events"


def load_config():
    with open("config.yml") as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


async def recv_loop(ws, duration, label):
    end = asyncio.get_event_loop().time() + duration
    count = 0
    while asyncio.get_event_loop().time() < end:
        remaining = end - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=min(remaining, 2))
        except asyncio.TimeoutError:
            print(f"[{ts()}] ({label}) timeout")
            continue
        except Exception as e:
            print(f"[{ts()}] ({label}) recv error: {e}")
            break

        count += 1
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = msg.json()
            event = data.get("event", "?")
            lifecycle = data.get("lifecycle_phase", "?")
            dump = json.dumps(data)
            if len(dump) < 600:
                print(f"[{ts()}] ({label}) MSG#{count} event={event} lifecycle={lifecycle}: {dump}")
            else:
                print(f"[{ts()}] ({label}) MSG#{count} event={event} lifecycle={lifecycle}")
                # Print summary
                if event == "change_mode":
                    print(f"  mode={data.get('mode')} status={data.get('status')} stations={data.get('stations')}")
                elif event == "device_status":
                    s = data.get("status", {})
                    print(f"  device={data.get('device_id')} relay={s.get('relay_state')} watering={s.get('watering_status')} flow={s.get('flow_status')}")
                elif event == "timer_program":
                    print(f"  program={data.get('program')} enabled={data.get('enabled')}")
                elif event == "smart_watering":
                    print(f"  schedule updates present")
                else:
                    print(f"  keys={list(data.keys())}")
        elif msg.type == aiohttp.WSMsgType.CLOSE:
            print(f"[{ts()}] ({label}) CLOSE (data={msg.data})")
            break
        elif msg.type == aiohttp.WSMsgType.CLOSED:
            print(f"[{ts()}] ({label}) CLOSED (data={msg.data})")
            break
        elif msg.type == aiohttp.WSMsgType.ERROR:
            print(f"[{ts()}] ({label}) ERROR: {ws.exception()}")
            break
    return count


async def main():
    print(f"[{ts()}] Starting debug_ws.py")
    print(f"[{ts()}] Device ID: {CONFIG['device_id']}, Zone: {CONFIG['zone_number']}")

    async with aiohttp.ClientSession() as session:
        print(f"[{ts()}] Logging in...")
        payload = {"session": {"email": CONFIG["bhyve_email"], "password": CONFIG["bhyve_password"]}}
        async with session.post(f"{BHYVE_API}/session", json=payload) as r:
            data = await r.json()
            if r.status >= 400:
                print(f"[{ts()}] Login FAILED ({r.status}): {data}")
                sys.exit(1)
            token = data["orbit_session_token"]
            print(f"[{ts()}] Login OK, token={token[:30]}...")

        # Connect WebSocket (NO header - token in app_connection body)
        print(f"[{ts()}] Connecting WebSocket...")
        ws = await session.ws_connect(BHYVE_WS)
        print(f"[{ts()}] Connected")

        # Send app_connection WITH token in body
        print(f"[{ts()}] Sending app_connection with token in body...")
        await ws.send_json({"event": "app_connection", "orbit_session_token": token})

        # Phase 1: Read 10 seconds
        print(f"[{ts()}] === Phase 1: 10s ===")
        c1 = await recv_loop(ws, 10, "P1")
        print(f"[{ts()}] === Phase 1 done ({c1} msgs) ===")

        if ws.closed:
            print(f"WebSocket closed during phase 1")
            return

        # Phase 2: Send change_mode and read 15s
        ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        change_payload = {
            "event": "change_mode",
            "mode": "manual",
            "device_id": CONFIG["device_id"],
            "timestamp": ts_now,
            "stations": [{"station": CONFIG["zone_number"], "run_time": 1}],
        }
        print(f"[{ts()}] Sending change_mode...")
        await ws.send_json(change_payload)

        print(f"[{ts()}] === Phase 2: 15s ===")
        c2 = await recv_loop(ws, 15, "P2")
        print(f"[{ts()}] === Phase 2 done ({c2} msgs) ===")

        if ws.closed:
            print(f"WebSocket closed during phase 2")
            return

        # Phase 3: Send stop and read 5s
        ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        stop_payload = {
            "event": "change_mode",
            "mode": "manual",
            "device_id": CONFIG["device_id"],
            "timestamp": ts_now,
            "stations": [],
        }
        print(f"[{ts()}] Sending stop...")
        await ws.send_json(stop_payload)

        print(f"[{ts()}] === Phase 3: 5s ===")
        c3 = await recv_loop(ws, 5, "P3")
        print(f"[{ts()}] === Phase 3 done ({c3} msgs) ===")

        print(f"[{ts()}] Totals: P1={c1} P2={c2} P3={c3}")
        await ws.close()
        print(f"[{ts()}] Done.")


if __name__ == "__main__":
    asyncio.run(main())
