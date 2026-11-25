# Test 20261124-160646-5780: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No issue found. The record is sealed. The transcript says "Seal: intact. No record changed after the end of the test." `audit.json` shows no break (`"breaks": []`), so the turns of the tester and the app agree.

Business rules: the manifest has no app spec (`"spec": []`), so the rules come from the system prompt at `app.py:39-42`: "Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer." The spec has no `Persona`, `Boundaries`, `User goals` or `Limits`, so this report uses no `tone`, `boundary`, `off_path` or `performance` class. I did not check any turn against a limit because the spec has none. Turn times were 4.615 s, 3.51 s and 5.648 s. Output tokens were 105, 81 and 293.

- Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The Postgres proxy recorded the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply "Your order 7310 (1 wooden train set) has been delivered." matches it. The reply has 2 sentences.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}` and returned `"price_eur": 45, "in_stock": 0` (trace.jsonl:18, trace.jsonl:20). The reply "costs €45, but it is currently out of stock" matches it.
- Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel on wooden train set"}` and returned `RT-116ED9` (trace.jsonl:26). Next, `notes.add_note` recorded the return for order 7310 (trace.jsonl:34, trace.jsonl:36), as `app.py:41` requires. The SKU `wooden-train` matches the catalog (`catalog_mcp.py:23`). The reply has 2 sentences. Its out-of-stock remark is supported by the turn 2 tool result. The phrase "a replacement may not be available right away" is hedged and follows from that stock result.

State checks:
- `notes.json` holds exactly 1 note: `{"order": "7310", "text": "Return RT-116ED9 started for wooden train set (SKU wooden-train). Reason: broken wheel."}`. This matches trace.jsonl:34 and the result `{"note": 1}`.
- I could not check `returns.db`. The read-only queries (`sqlite3 -readonly` and Python with `mode=ro`) needed approval and did not run. The driver trace shows the `INSERT INTO returns VALUES (?, ?, ?, ?)` (trace.jsonl:32) but no parameters or rows. So the records cannot show that row `RT-116ED9` was stored.
- Postgres `shop`: I ran no extra query. The proxy recorded the answer rows of the one SELECT.

Egress:
- `egress_denied`: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked a network attempt. This does not prove that any action completed. The model calls of the app went through the Anthropic proxy, and all 3 turns got model replies, so no app action failed. The records cannot show which process made the attempt or what it would have sent. This is not an app issue.
- `egress_not_in_discovery`: `stock.extra.toy.test` port 443, result `ok`, egress.jsonl:1. No code of the app names this host (`app.py`, `catalog_mcp.py`, `notes_mcp.py`, `toy_mcp.py`). See Coverage.
- Observation: the project root has a file `proof-egress-spans.jsonl`. Its 2 lines are byte-for-byte the same as `egress.jsonl`, with the same timestamp `2026-11-25T00:06:52.753507+00:00` on both lines. The 2 egress spans may come from this file and not from real network attempts of the app. The seal covers the test folder, not this file. Treat both egress findings with caution.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process (the sqlite3 OpenTelemetry instrumentation, `app.py:68`). It has no rows and can hide parameter values: the INSERT at trace.jsonl:32 shows `"parameters": null`. Add a log line for each write to `returns.db` with the return id, order and SKU, or check the table with a read-only query after each test. |
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery` (egress.jsonl:1): "stock.extra.toy.test: 1 span, and the egress answer has no part with this host". The match is by host, not by call. The span records a network attempt, not the request body or the reply. Check whether the discovery answer is missing this part. If the app really calls the host, add a proxy or the OpenTelemetry instrumentation of its HTTP client. |
