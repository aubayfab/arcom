"""Subscribe to all notify/indicate characteristics and log state + changes.

Usage: python monitor.py <MAC> [seconds] [label]
Read-only: subscribes and reads, never writes a command channel.
Also dumps a full snapshot of every readable characteristic at start and end,
written to snapshot_<label>.json for diffing.
"""
import asyncio
import json
import sys
from datetime import datetime

from bleak import BleakClient

if len(sys.argv) < 2:
    sys.exit(__doc__)
ADDR = sys.argv[1]
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
LABEL = sys.argv[3] if len(sys.argv) > 3 else datetime.now().strftime("%H%M%S")


def short(uuid):
    u = str(uuid).lower()
    return u[4:8] if u.endswith("-0000-1000-8000-00805f9b34fb") else u[-4:]


async def snapshot(client):
    snap = {}
    for service in client.services:
        for c in service.characteristics:
            if "read" in c.properties:
                try:
                    raw = await client.read_gatt_char(c)
                    snap[short(c.uuid)] = raw.hex()
                except Exception as e:
                    snap[short(c.uuid)] = f"ERR:{e}"
    return snap


async def main():
    last = {}
    print(f"Connecting to {ADDR} ...", file=sys.stderr)
    async with BleakClient(ADDR, timeout=25.0) as client:
        print(f"Connected: {client.is_connected}", file=sys.stderr)

        snap_start = await snapshot(client)
        with open(f"snapshot_{LABEL}.json", "w") as f:
            json.dump(snap_start, f, indent=2, sort_keys=True)
        print(f"Snapshot -> snapshot_{LABEL}.json ({len(snap_start)} chars)\n", file=sys.stderr)

        def make_cb(key):
            def cb(_, data):
                h = data.hex()
                prev = last.get(key)
                if h != prev:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"[{ts}] {key}  {prev} -> {h}", flush=True)
                    last[key] = h
            return cb

        subscribed = 0
        for service in client.services:
            for c in service.characteristics:
                if "notify" in c.properties or "indicate" in c.properties:
                    try:
                        await client.start_notify(c, make_cb(short(c.uuid)))
                        subscribed += 1
                    except Exception as e:
                        print(f"  subscribe {short(c.uuid)} failed: {e}", file=sys.stderr)
        print(f"Subscribed to {subscribed} characteristics. Watching {DURATION:.0f}s...\n", file=sys.stderr, flush=True)

        # Poll readable datapoint-table chars too, in case they update without notifying
        poll_keys = ["7c86", "7c87", "7c88", "7c89", "7c6f", "7c7d", "7c6d", "7c69"]
        step = 2.0
        waited = 0.0
        while waited < DURATION:
            await asyncio.sleep(step)
            waited += step
            for service in client.services:
                for c in service.characteristics:
                    k = short(c.uuid)
                    if k in poll_keys and "read" in c.properties:
                        try:
                            raw = (await client.read_gatt_char(c)).hex()
                        except Exception:
                            continue
                        pk = "poll:" + k
                        if last.get(pk) not in (None, raw):
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            print(f"[{ts}] {pk}  {last[pk]} -> {raw}", flush=True)
                        last[pk] = raw

        snap_end = await snapshot(client)
        with open(f"snapshot_{LABEL}_end.json", "w") as f:
            json.dump(snap_end, f, indent=2, sort_keys=True)
        print(f"\nEnd snapshot -> snapshot_{LABEL}_end.json", file=sys.stderr)
        print("Done.", file=sys.stderr)


asyncio.run(main())
