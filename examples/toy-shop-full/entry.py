"""The entry of the full toy shop: agent contract v1 on stdin and stdout.

The tap starts it at `verbatim-relay start` (SPEC.md section 6). It needs claude-agent-sdk.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from app import Shop

from verbatim_relay import contract


async def main() -> None:
    # Only contract lines go to stdout. The rest of the output goes to stderr (app.log).
    out = os.fdopen(os.dup(1), "wb", buffering=0)
    os.dup2(2, 1)
    loop = asyncio.get_running_loop()
    async with Shop() as shop:
        while raw := await loop.run_in_executor(None, sys.stdin.buffer.readline):
            rid, message, _ = contract.parse_request(raw.removesuffix(b"\n"))
            try:
                row = {"v": 1, "id": rid, "reply": await shop.reply(message)}
            except Exception as e:  # the contract has an error line for this
                row = {"v": 1, "id": rid, "error": f"{type(e).__name__}: {e}"}
            out.write(json.dumps(row, ensure_ascii=False).encode() + b"\n")


if __name__ == "__main__":
    asyncio.run(main())
