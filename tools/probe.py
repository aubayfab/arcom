"""Decisive non-disruptive test: does the module execute our command frames?

Sends a temperature-offset command and checks whether the readable state
characteristic (READ_COMMAND, ...c69) reflects the change. Restores the original
offset afterwards. Offset is just a comfort setpoint, instantly reverted.

Usage: python probe.py <MAC> [--pad]
"""
import asyncio
import sys

from bleak import BleakClient

WRITE_COMMAND = "854dbb8e-f11e-11e5-9ce9-5e5517507c67"
READ_COMMAND = "854dbb8e-f11e-11e5-9ce9-5e5517507c69"
TEMP_OFFSET = 0xD0  # | 0..12 (6 = neutral setpoint)

if len(sys.argv) < 2:
    sys.exit(__doc__)
addr = sys.argv[1]
pad = "--pad" in sys.argv


def frame(cmd):
    b = bytes([cmd])
    return b + bytes(4) if pad else b


async def read_state(client, label):
    v = await client.read_gatt_char(READ_COMMAND)
    vals = list(v)
    occ = vals[0] if len(vals) > 0 else None
    vent = vals[1] if len(vals) > 1 else None
    off = vals[2] if len(vals) > 2 else None
    print(f"  {label}: {v.hex()}   -> occupation={occ} ventilation={vent} offsetTemp={off}")
    return vals


async def main():
    print(f"Connecting to {addr} ... (pad={pad})")
    async with BleakClient(addr, timeout=25.0) as client:
        print(f"Connected: {client.is_connected}")
        before = await read_state(client, "before     ")
        orig_off = before[2] if len(before) > 2 else 6

        target = 8 if orig_off != 8 else 4
        print(f">>> sending OFFSETTEMP = {target}  (byte 0x{TEMP_OFFSET | target:02X})")
        await client.write_gatt_char(WRITE_COMMAND, frame(TEMP_OFFSET | target), response=True)
        await asyncio.sleep(1.5)
        after = await read_state(client, "after cmd  ")

        print(f">>> restoring OFFSETTEMP = {orig_off}  (byte 0x{TEMP_OFFSET | orig_off:02X})")
        await client.write_gatt_char(WRITE_COMMAND, frame(TEMP_OFFSET | orig_off), response=True)
        await asyncio.sleep(1.0)
        await read_state(client, "after restore")

        changed = len(after) > 2 and after[2] == target
        print()
        if changed:
            print(f"RESULT: *** COMMAND EXECUTED *** offsetTemp changed {orig_off} -> {after[2]}")
            print("        => The module DOES honor our frames. Light/blind issue is physical mapping.")
        else:
            print("RESULT: no state change observed -> module did not apply the command"
                  + ("" if pad else " (try --pad)"))


asyncio.run(main())
