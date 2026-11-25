# Test 20261124-163743-7bf7: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

The seal was intact and the relay audit showed no breaks. I found no app issues in the three turns.

- Turn 1 matched the recorded Postgres row for order `7310` (`"delivered"`, `"1 wooden train set"`, `trace.jsonl:11`). The live Postgres lookup could not be repeated because `psql` was unavailable.
- Turn 2 matched the catalog result of `"price_eur": 45` and `"in_stock": 0` (`trace.jsonl:20`, `catalog_mcp.py:23`).
- Turn 3 persisted return `RT-4526AA` for order `7310`, SKU `wooden-train`, and reason `Broken wheel on wooden train set`, verified with a read-only SQLite query. The support note in `notes.json` matched `trace.jsonl:36` and fulfilled the rule at `app.py:41`. All three replies met the two-sentence rule on that line.
- The policy blocked a connection attempt to `api.anthropic.com:8443` in turn 1 for reason `port` (`egress.jsonl:2`). The records give no request payload or purpose for that attempt. The order lookup and reply succeeded, and the record establishes no app defect from the denial.
- No app-state snapshot or spec Limits table was available. The transcript recorded 4.453, 4.083, and 6.729 seconds and 81, 81, and 280 model output tokens for turns 1–3, respectively.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery` at `egress.jsonl:1` records a connection attempt. Request and reply details are unavailable. Check the discovery answer and use a proxy or client instrumentation for the host. |
| returns | database | driver trace | The trace comes from the app process, has no rows, and can hide parameter values. Use a read-only SQLite query to verify persisted rows. |
