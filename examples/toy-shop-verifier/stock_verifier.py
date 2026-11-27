"""Verify one claim against the toy shop's stock counts."""

import json
import re
import sys

# The verifier has an old count for the kite. The claim set gives the current count.
STOCK = {"blue mug": 4, "teddy bear": 8, "kite": 2, "train": 6, "puzzle": 5}


def main() -> None:
    claim = json.loads(sys.stdin.buffer.readline())
    match = re.fullmatch(r"The (.+) has ([0-9]+) in stock\.", claim["text"])
    supported = bool(match and STOCK.get(match[1]) == int(match[2]))
    print(json.dumps({"verdict": "supported" if supported else "refuted"}))


if __name__ == "__main__":
    main()
