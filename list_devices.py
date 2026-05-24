import asyncio
import aiohttp
import yaml
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yml")

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

BHYVE_API = "https://api.orbitbhyve.com/v1"


async def main():
    async with aiohttp.ClientSession() as session:
        payload = {
            "session": {
                "email": config["bhyve_email"],
                "password": config["bhyve_password"],
            }
        }
        async with session.post(f"{BHYVE_API}/session", json=payload) as r:
            data = await r.json()
            if r.status >= 400 or "orbit_session_token" not in data:
                print(f"Login failed ({r.status}): {data}")
                return
            token = data["orbit_session_token"]

        headers = {"Orbit-Session-Token": token}
        async with session.get(f"{BHYVE_API}/devices", headers=headers) as r:
            devices = await r.json()

        for d in devices:
            print(f"Device: {d.get('name', '(unnamed)')}")
            print(f"  ID: {d['id']}")
            print(f"  Type: {d.get('type', 'N/A')}")
            zones = d.get("zones", [])
            if zones:
                print("  Zones:")
                for i, z in enumerate(zones, 1):
                    name = z.get("name", f"Zone {i}")
                    enabled = "enabled" if z.get("enabled") else "disabled"
                    print(f"    {i}: {name} ({enabled})")
            print()


if __name__ == "__main__":
    asyncio.run(main())
