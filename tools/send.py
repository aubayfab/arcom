"""Send one or more command payloads to an Arcom module's WRITE_COMMAND characteristic.

Usage:
  python send.py <MAC> <hex1> [<hex2> ...] [--pad] [--delay 2.0]

Each <hexN> is written (with response) to the command characteristic (...c67), in order,
with --delay seconds between writes. --pad appends 00 00 00 00 (default-PIN "0000")
to each payload, replicating the app when a PIN is stored.

Replicates exactly what the official myArcom app writes. No fuzzing.
"""
import asyncio
import sys

from bleak import BleakClient

WRITE_COMMAND = "854dbb8e-f11e-11e5-9ce9-5e5517507c67"
READ_COMMAND = "854dbb8e-f11e-11e5-9ce9-5e5517507c69"

args = sys.argv[1:]
pad = "--pad" in args
if pad:
    args.remove("--pad")
delay = 2.0
if "--delay" in args:
    i = args.index("--delay")
    delay = float(args[i + 1])
    del args[i:i + 2]

if len(args) < 2:
    sys.exit(__doc__)
addr = args[0]
payloads = []
for h in args[1:]:
    b = bytes.fromhex(h)
    if pad:
        b = b + bytes(4)  # "0000" PIN -> 00 00 00 00
    payloads.append(b)


async def main():
    print(f"Connecting to {addr} ...")
    async with BleakClient(addr, timeout=25.0) as client:
        print(f"Connected: {client.is_connected}")
        # Show current read-command state for context
        try:
            st = await client.read_gatt_char(READ_COMMAND)
            print(f"READ_COMMAND state before: {st.hex()}")
        except Exception as e:
            print(f"(could not read state: {e})")

        for idx, p in enumerate(payloads):
            print(f">>> writing {p.hex()} to WRITE_COMMAND ...")
            await client.write_gatt_char(WRITE_COMMAND, p, response=True)
            print("    OK (write acknowledged)")
            if idx != len(payloads) - 1:
                await asyncio.sleep(delay)
        print("Done.")


asyncio.run(main())
