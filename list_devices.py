import asyncio
import aiohttp
import yaml
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import state

async def main():
    path = state.get_config_path()
    if not os.path.exists(path):
        email = input("B-hyve email: ").strip()
        password = input("B-hyve password: ").strip()
    else:
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
        email = cfg.get("bhyve_email") or input("B-hyve email: ").strip()
        password = cfg.get("bhyve_password") or input("B-hyve password: ").strip()

    async with aiohttp.ClientSession() as session:
        url = "https://api.orbitbhyve.com/v1/session"
        payload = {"session": {"email": email, "password": password}}
        async with session.post(url, json=payload) as r:
            if r.status >= 400:
                data = await r.json()
                print(f"Login failed ({r.status}): {data}")
                return
            data = await r.json()
            token = data["orbit_session_token"]

        headers = {"Authorization": f"Bearer {token}"}
        async with session.get("https://api.orbitbhyve.com/v1/devices", headers=headers) as r:
            devices = await r.json()
            print("\nDevices:")
            for d in devices:
                print(f"  {d.get('description', '?')} (id={d.get('_id', '?')})")
                zones = d.get("zones", [])
                print(f"    Zones: {len(zones)}")
                for z in zones:
                    print(f"      {z.get('name', '?')} (station={z.get('station', '?')})")

if __name__ == "__main__":
    asyncio.run(main())
