"""An entry for the toy shop HTTP agent at a cluster Service. It sends each message to the Service.

The agent runs in its own pod, behind a Service, for example in a Koodam Workspace
(docs/getting-started-cluster.md). The entry starts no server. It reads the URL of the agent
from TOY_SHOP_URL. If the egress answer has a backend with this variable, the test gives the
variable the URL of a recording proxy, so the backend record has each call. It imports nookku, so
the entry gets nookku with uv:

    {"entry": ["uv", "run", "--with", "nookku", "python3", "service_entry.py"]}
"""

from __future__ import annotations

import json
import os
import urllib.request

from nookku.agent import serve

URL = os.environ.get("TOY_SHOP_URL", "http://toy-shop.shop.svc:8080/")


def reply(message: str, history: list[tuple[str, str]]) -> str:
    body = json.dumps({"text": message}).encode()
    request = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    # 200 s is less than the 240 s of the tap, so the tester gets this error and not a timeout.
    with urllib.request.urlopen(request, timeout=200) as response:
        text: str = json.loads(response.read())["reply"]
        return text


serve(reply)
