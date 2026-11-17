# Test 20261117-154442-e219: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- Seal: "Seal: intact. No record changed after the end of the test." `audit.json` has no break (`"breaks": []`), so the turns of `relay.jsonl` and the transcript agree.
- I found no issue of the app in the 3 turns.
- Business rules: the app spec has no files (`"spec": []` in `manifest.json`), so I took the rules from the system prompt at `app.py:39-42`: "Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer."
  - Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The proxy shows the query with `["7310"]`, which returned `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply says "Your order 7310 (1 wooden train set) has been delivered." That matches the result, and it is 2 sentences.
  - Turn 2: `catalog.find_product` got `{"name": "wooden train"}`, which returned `"price_eur": 45, "in_stock": 0` (trace.jsonl:18, and the MCP proxy at trace.jsonl:20). The reply "costs €45, but it is currently out of stock" matches the result, and it is 2 sentences.
  - Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel"}` and returned `RT-16C9A3` (trace.jsonl:26). The sku comes from the catalog result of turn 2. Next, `notes.add_note` was called for order 7310 (trace.jsonl:34, trace.jsonl:36), as the rule requires. The reply is 2 sentences and matches both results.
- State: `notes.json` holds 1 note for order 7310 with the same text as trace.jsonl:34. The hook denied `sqlite3` and `python3` against `returns.db`, so I could not run a SELECT on it. A byte search (grep) of `returns.db` finds `RT-16C9A3`, `7310`, `wooden-train` and `Broken wheel` stored together, which agrees with the INSERT of trace.jsonl:32. The driver trace has no parameters, so this byte search is the only state check I could do for the return.
- Performance: the manifest has no `Limits` (`"limits": {}`), so I checked no limit. For reference: turn 1 took 3.226 s / 108 output tokens, turn 2 took 2.28 s / 93, and turn 3 took 3.848 s / 278.
- No spec means no `Persona`, `Boundaries` or `User goals`, so I did not judge `tone`, `boundary` or `off_path`.
- `egress_denied`: host `api.anthropic.com`, reason `port` (connect to port 8443), egress.jsonl:2, turn 1. The app's model traffic goes through the `anthropic` proxy (`ANTHROPIC_BASE_URL`), all 3 turns got model replies, and no app code names port 8443. The records cannot show which process made the attempt or what it was for. I did not count it as an app issue.
- `egress_not_in_discovery`: `stock.extra.toy.test` port 443, `result: ok` (egress.jsonl:1). No app file names this host. Both egress spans have the same timestamp (`2026-11-17T10:14:48.038770`, 6 ms after the turn 1 reply). They are also byte-for-byte the same as `proof-egress-spans.jsonl` in the project root. This suggests the spans were injected for a proof setup, not made by the app. The seal covers the records, so I report them as they are.
- The test folder has no `app-state/`.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process (SQLite3Instrumentor, `app.py:68`). It has no rows and hides parameter values (`"parameters": null` at trace.jsonl:32). To record each row, log one line per return in `start_return` with its id, order, sku and reason, or point the app at a database that a proxy can see. |
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery`, egress.jsonl:1: 1 connect to port 443, and no part of the egress answer has this host. Check the discovery answer: if the app really calls this host, add it as a part, and add a proxy or the OpenTelemetry instrumentation of its HTTP client. The span records a network attempt, not the request body or the reply. |
