"""Scan BLE advertisements and dump everything seen, to identify Arcom devices."""
import asyncio
import json
import sys
from datetime import datetime

from bleak import BleakScanner

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0

seen = {}


def on_adv(device, adv):
    entry = seen.setdefault(device.address, {
        "address": device.address,
        "names": set(),
        "rssi_max": -999,
        "count": 0,
        "manufacturer_data": {},
        "service_data": {},
        "service_uuids": set(),
        "tx_power": None,
    })
    entry["count"] += 1
    if adv.local_name:
        entry["names"].add(adv.local_name)
    if device.name:
        entry["names"].add(device.name)
    entry["rssi_max"] = max(entry["rssi_max"], adv.rssi)
    for cid, data in adv.manufacturer_data.items():
        entry["manufacturer_data"].setdefault(f"0x{cid:04X}", set()).add(data.hex())
    for uuid, data in adv.service_data.items():
        entry["service_data"].setdefault(uuid, set()).add(data.hex())
    entry["service_uuids"].update(adv.service_uuids)
    if adv.tx_power is not None:
        entry["tx_power"] = adv.tx_power


async def main():
    print(f"Scanning {DURATION:.0f}s...", file=sys.stderr)
    async with BleakScanner(detection_callback=on_adv, scanning_mode="active"):
        await asyncio.sleep(DURATION)

    def ser(o):
        if isinstance(o, set):
            return sorted(o)
        raise TypeError

    devices = sorted(seen.values(), key=lambda e: -e["rssi_max"])
    out = f"scan_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(devices, f, default=ser, indent=2)

    for e in devices:
        names = ",".join(sorted(e["names"])) or "-"
        mfr = "; ".join(f"{k}:{'|'.join(sorted(v))[:60]}" for k, v in e["manufacturer_data"].items())
        svc = ",".join(sorted(e["service_uuids"]))
        sd = "; ".join(f"{k[4:8]}:{'|'.join(sorted(v))[:40]}" for k, v in e["service_data"].items())
        print(f"{e['address']}  rssi={e['rssi_max']:>4}  n={e['count']:>3}  name={names!r}")
        if mfr:
            print(f"    mfr: {mfr}")
        if svc:
            print(f"    svc: {svc}")
        if sd:
            print(f"    sd : {sd}")
    print(f"\n{len(devices)} devices -> {out}", file=sys.stderr)


asyncio.run(main())
