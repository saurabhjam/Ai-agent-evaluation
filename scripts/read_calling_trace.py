"""Read calling diagnostics downloaded from the existing evaluation log endpoint."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--decrypt", action="store_true", help="Explicitly display personal text using the private environment key")
    args = parser.parse_args()
    cipher = None
    if args.decrypt:
        from cryptography.fernet import Fernet

        cipher = Fernet(os.environ["CALLING_DIAGNOSTICS_ENCRYPTION_KEY"].encode("ascii"))
    for line in args.path.read_text(encoding="utf-8").splitlines():
        start = line.find('{"schema": "calling.turn.v1"')
        if start < 0:
            continue
        event = json.loads(line[start:])
        encrypted = event.pop("encrypted_data", None)
        if cipher and encrypted:
            event["private_data"] = json.loads(cipher.decrypt(encrypted.encode("ascii")))
        print(json.dumps(event, ensure_ascii=True))


if __name__ == "__main__":
    main()
