"""Version 1 of the toy shop agent of the rollout example. It asks the stock service for the
blue mug, and gives the count in each reply. It uses no model."""

import json
import os
import sys
import urllib.request

for raw in sys.stdin.buffer:
    request = json.loads(raw)
    url = os.environ["STOCK_URL"] + "/stock?sku=blue-mug"
    with urllib.request.urlopen(url, timeout=10) as response:
        left = json.loads(response.read())["left"]
    text = f"You said: {request['message']} The shop has {left} blue mugs."
    reply = {"v": 1, "id": request["id"], "reply": text}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
