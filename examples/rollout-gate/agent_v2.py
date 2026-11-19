"""Version 2 of the toy shop agent of the rollout example, with a planted defect. It asks the
stock service for a product that the service does not know, so each turn has a backend call
with status 503. The reply does not show the defect. It uses no model."""

import contextlib
import json
import os
import sys
import urllib.error
import urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    url = os.environ["STOCK_URL"] + "/stock?sku="
    with urllib.request.urlopen(url + "blue-mug", timeout=10) as response:
        left = json.loads(response.read())["left"]
    # The planted defect.
    with contextlib.suppress(urllib.error.HTTPError):
        urllib.request.urlopen(url + "gift-card", timeout=10).close()
    text = f"You said: {request['message']} The shop has {left} blue mugs."
    reply = {"v": 1, "id": request["id"], "reply": text}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
