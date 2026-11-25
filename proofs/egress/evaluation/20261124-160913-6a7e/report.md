# Test 20261124-160913-6a7e: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 3 | turn 3, trace.jsonl:38 | The reply says "Please keep the train set for the return process." No tool result and no rule supports this. The `start_return` result (trace.jsonl:26) is only `{"return": "RT-BE3C41", "order": "7310", "sku": "wooden-train"}`, and the system prompt (app.py:39-42) says nothing about what the customer must do with the item. |

## Notes

- Seal: "Seal: intact. No record changed after the end of the test." The audit shows no break (`"breaks": []`), and the 3 turns of the relay match the 3 turns of the transcript.
- The app spec is empty (`"spec": []` in manifest.json). That means there is no `Persona`, `Boundaries`, `User goals` or `Limits` part, so I did not judge `tone`, `boundary`, `off_path` or `performance`. The only business rules are in the system prompt, app.py:39-42: "Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer."
- Turn 1: `shop.lookup_order` got `{"order": "7310"}`, which is the right order. The Postgres proxy recorded the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11), and the reply matches it. The reply has 2 sentences.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}`, and the MCP proxy recorded the result `price_eur: 45, in_stock: 0` (trace.jsonl:20). The reply "costs €45, but it is currently out of stock" matches it and agrees with catalog_mcp.py:23.
- Turn 3: `shop.start_return` got `order 7310, sku wooden-train` and a fitting reason (trace.jsonl:26). After it, `notes.add_note` ran as the rule needs (trace.jsonl:34-36). The project file `notes.json` holds this one note, which agrees with the trace. The reply has 2 sentences. The only issue is the unsupported instruction in the table.
- State of `returns`: the driver trace shows `CREATE` and `INSERT INTO returns VALUES (?, ?, ?, ?)` with hidden parameters (trace.jsonl:30-32). I tried a read-only `sqlite3 -readonly returns.db "SELECT * FROM returns;"`, but the command was not approved. So I could not confirm that row `RT-BE3C41` is in `returns.db`. The tool result and the code (app.py:96-112, with `db.commit()`) suggest that the row was written, but the records cannot prove it.
- egress_denied: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked a connect attempt. It does not prove that any action completed. Turn 1 still got a model reply (2 model calls in performance), and no app code names this port. The records cannot show which process made the attempt or why. This is not an app issue.
- egress_not_in_discovery: `stock.extra.toy.test` port 443, result `ok` (egress.jsonl:1). This happened at 00:09:19.79, right after the reply of turn 1. None of app.py, catalog_mcp.py, notes_mcp.py, toy_mcp.py or entry.py names this host. The records do not show the request or the reply, so I cannot say what the call did.
- No `unseen_call` finding, and `unseen` is empty.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery` (egress.jsonl:1). The discovery answer has no part with this host. The match is by host, and the span records a network attempt, not the request body or the reply. Check the discovery answer, and add this host as a part that goes through a proxy, or add OpenTelemetry instrumentation of the HTTP client that calls it. |
| returns | database | driver trace | The driver trace comes from the app process (the sqlite3 instrumentation, app.py:68). It has no rows and can hide parameter values (here `parameters: null`, trace.jsonl:32). Check the state with a read-only query, or record the rows of each answer with a log line per query. |
