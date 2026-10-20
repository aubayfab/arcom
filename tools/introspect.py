"""Connect to one BLE device and dump its full GATT table (read-only introspection).

Usage: python introspect.py <MAC>
Reads every readable characteristic/descriptor. Makes no writes.
"""
import asyncio
import sys

from bleak import BleakClient

if len(sys.argv) < 2:
    sys.exit(__doc__)
ADDR = sys.argv[1]

# Known SIG UUID short-name hints
KNOWN = {
    "2a00": "Device Name", "2a01": "Appearance", "2a04": "Pref Conn Params",
    "2a05": "Service Changed", "2a19": "Battery Level", "2a23": "System ID",
    "2a24": "Model Number", "2a25": "Serial Number", "2a26": "Firmware Rev",
    "2a27": "Hardware Rev", "2a28": "Software Rev", "2a29": "Manufacturer",
    "2a50": "PnP ID", "2902": "CCCD", "2901": "User Description",
}


def short(uuid):
    u = str(uuid).lower()
    if u.endswith("-0000-1000-8000-00805f9b34fb"):
        return u[4:8]
    return u


def props(c):
    return ",".join(c.properties)


async def main():
    print(f"Connecting to {ADDR} ...", file=sys.stderr)
    async with BleakClient(ADDR, timeout=25.0) as client:
        print(f"Connected: {client.is_connected}\n")
        for service in client.services:
            print(f"SERVICE {short(service.uuid)}  {service.description}")
            for c in service.characteristics:
                s = short(c.uuid)
                hint = KNOWN.get(s, "")
                line = f"  CHAR {s}  [{props(c)}]  {c.description} {hint}".rstrip()
                val_repr = ""
                if "read" in c.properties:
                    try:
                        raw = await client.read_gatt_char(c)
                        txt = ""
                        try:
                            dec = raw.decode("utf-8")
                            if all(32 <= ord(ch) < 127 or ch in "\r\n\t" for ch in dec):
                                txt = f"  text={dec!r}"
                        except Exception:
                            pass
                        val_repr = f"  = {raw.hex()}{txt}"
                    except Exception as e:
                        val_repr = f"  (read failed: {e})"
                print(line + val_repr)
                for d in c.descriptors:
                    ds = short(d.uuid)
                    try:
                        dval = await client.read_gatt_descriptor(d.handle)
                        print(f"    DESC {ds} {KNOWN.get(ds,'')} = {dval.hex()}")
                    except Exception:
                        print(f"    DESC {ds} {KNOWN.get(ds,'')}")
        print("\nDone.", file=sys.stderr)


asyncio.run(main())
