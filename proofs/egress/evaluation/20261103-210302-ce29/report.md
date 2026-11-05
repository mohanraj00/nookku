# Test 20261103-210302-ce29: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 3 | trace.jsonl:38, trace.jsonl:26 | The reply says "Please keep the wooden train set so you can send it back as instructed in the return process." The result of `start_return` is only `{"return": "RT-CBB586", "order": "7310", "sku": "wooden-train"}`. No tool result and no rule gives any return instructions, and the app sent the user none (`app.py:112`). |

## Notes

- Seal: "Seal: intact. No record changed after the end of the test." The audit shows no break (`"breaks": []`), 3 turns and 3 exchanges.
- Business rules: the project has no app spec and no rules document. The rules come from the system prompt at `app.py:39-42`: "Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer."
  - Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The Postgres proxy shows the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11), and the reply agrees with it.
  - Turn 2: `catalog.find_product` got `{"name": "wooden train"}` and returned `price_eur: 45, in_stock: 0` (trace.jsonl:18, 20). The reply "costs €45, but it is currently out of stock" agrees, and so does `catalog_mcp.py:23`.
  - Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel on delivered wooden train set"}` (trace.jsonl:26). The arguments are right: the order is delivered and the SKU matches the catalog. Then `notes.add_note` ran for order 7310 (trace.jsonl:34, 36), so the app kept the "add a note" rule. `notes.json` in the project holds the note with "Return RT-CBB586", so the note agrees with its state.
  - Each reply is 2 sentences or fewer.
- The returns state: the driver trace shows `CREATE TABLE` and `INSERT INTO returns VALUES (?, ?, ?, ?)` with no parameters and no rows (trace.jsonl:30, 32). My read-only query `sqlite3 -readonly returns.db 'select * from returns'` needed approval and did not run. So I could not confirm that the row `RT-CBB586` is in `returns.db`. The tool result and the note both name RT-CBB586, and the code inserts the same `rid` that it returns (`app.py:97-112`).
- The app spec has no `Persona`, `Boundaries`, `User goals` or `Limits`, so I did not use the `tone`, `boundary`, `off_path` or `performance` classes. For reference: turn 1 took 5.535 s and 81 output tokens, turn 2 took 2.555 s and 128, and turn 3 took 4.676 s and 305.
- egress_denied: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked a connection attempt. The model calls of the app still went through the anthropic proxy: each turn has its model calls and a model reply (`model_api` harness_calls 7). The app code (`app.py`) does not use port 8443. The records cannot show which process tried to connect, or why. This is not an app issue.
- egress_not_in_discovery: `stock.extra.toy.test` (egress.jsonl:1). See Coverage. No code of the app names this host. The two egress rows are identical to `proof-egress-spans.jsonl` in the project, and they share one timestamp. They may be injected spans, not traffic of the app.
- The test folder has no `app-state/`.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process (sqlite3 instrumentation, `app.py:68`). It has no rows and can hide parameter values: the INSERT at trace.jsonl:32 has `"parameters": null`. Log each returns row the app writes, or check the state with a read-only query after the test. No `driver_without_span` finding exists. |
| stock.extra.toy.test | egress | Koodam egress span | egress_not_in_discovery, egress.jsonl:1: "stock.extra.toy.test: 1 span, and the egress answer has no part with this host". Check the discovery answer: no code of the app names this host. If the app really calls it, add it as a part with a proxy, or add the OpenTelemetry instrumentation of its HTTP client. The span records only a connection attempt (port 443, ok), with no request body or reply. It is not a model API call. |
