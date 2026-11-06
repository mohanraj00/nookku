# Test 20261103-210106-438d: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No issue found. The seal is intact ("Seal: intact. No record changed after the end of the test."), and the audit shows no break (`"breaks": []`), so the turns of `relay.jsonl` and the transcript agree.

The test has no app spec (`"spec": []` in `manifest.json`), so it has no `Persona`, `Boundaries`, `User goals` or `Limits`. Thus there is no `tone`, `boundary`, `off_path` or `performance` check. The business rules come from the system prompt at `app.py:39-41`: "Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer."

What I checked:

- Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6), the order the tester gave. The Postgres proxy shows the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply "Your order 7310 (1 wooden train set) has been delivered." agrees. 2 sentences.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}` (trace.jsonl:18). The MCP proxy shows `"price_eur": 45, "in_stock": 0` (trace.jsonl:20), and this agrees with `PRODUCTS` in `catalog_mcp.py`. The reply "costs €45, but it is currently out of stock" agrees. "I can't tell you when it will be restocked" is true: no tool gives a restock date. 2 sentences.
- Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel on wooden train set"}` (trace.jsonl:26). The order and the SKU match the results of turns 1 and 2. Then `notes.add_note` was called for order 7310 with the return id RT-925E5C (trace.jsonl:34, trace.jsonl:36), as the rule at `app.py:40` requires. `notes.json` in the project holds that note. The reply names RT-925E5C, the order, the reason and the note, and each fact comes from a tool result. 2 sentences.
- The SQLite `returns` database is seen only through a driver trace (trace.jsonl:30, trace.jsonl:32), with no rows and no parameter values. I tried to check the `returns` table with a read-only `sqlite3 -readonly` query, but that command was not approved. So the records cannot confirm that the row RT-925E5C is in `returns.db`. The tool result (trace.jsonl:26) and the code (`app.py:96-115`) agree that the insert ran and committed.
- Performance (no limits): turn 1 took 11.78 s and 106 output tokens, turn 2 took 4.824 s and 133 output tokens, and turn 3 took 5.181 s and 329 output tokens.

Denied egress:

- `egress_denied`: host `api.anthropic.com`, reason `port` (connect to port 8443), egress.jsonl:2, turn 1. The policy blocked a network attempt. It does not prove that any action finished. Each turn got its model replies through the Anthropic proxy (the model calls in `performance.json` and the replies at trace.jsonl:14, 22 and 38), and no tool or reply failed. Nothing in the app code (`app.py`, `catalog_mcp.py`, `notes_mcp.py`, `entry.py`) names port 8443. So this is not an app defect in the records. The records cannot show which process made the attempt or what it would have sent.

Other observation: the 2 egress spans in `egress.jsonl` have the same bytes as `proof-egress-spans.jsonl` in the project root, with the same timestamp `2026-11-03T15:31:21.215661+00:00` on both lines. No app code names `stock.extra.toy.test` or port 8443. The records cannot show if the app made these connections or if the spans came from somewhere else.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process (the sqlite3 OpenTelemetry instrumentation, `app.py:65`). It has no rows and can hide parameter values: the INSERT at trace.jsonl:32 shows `"parameters": null`. There is no `driver_without_span` finding: the trace has the CREATE and INSERT of turn 3. To record the rows, add a log line for each write with the values, or move the returns to a database that a proxy can record. |
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery` (egress.jsonl:1): "stock.extra.toy.test: 1 span, and the egress answer has no part with this host". It was a connect to port 443 that worked. The match is by host only, the span records a network attempt and not a request or a reply, and it is not a model API call. Check the discovery answer: add the host as a part if the app uses it, or find the process that connected. Then record it with a proxy or with the OpenTelemetry instrumentation of its HTTP client. |
