# Test 20261124-164810-6682: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- No app issues were found in the three recorded turns. The seal was intact, and the audit reported no breaks across the three exchanges.
- The Postgres proxy returned `["7310", "delivered", "1 wooden train set"]` in turn 1 (trace.jsonl:11). The catalog source and tool result agree on €45 and zero stock in turn 2 (trace.jsonl:20).
- A read-only SQLite query confirmed return `RT-230D78` for order `7310`, SKU `wooden-train`, with reason `Broken wheel on wooden train set`. The note in `notes.json` matches the write recorded in trace.jsonl:36 and satisfies the app's rule to add an order note after starting a return. All three replies observed the app's two-sentence limit.
- The test had no app-state snapshot or app spec with a Limits table. The turn-time and token counts therefore had no limits to check against. The live Postgres state was unavailable for a separate check because `psql` was unavailable. The order result was verified against the recorded proxy row.
- Turn 1 recorded a denied connection attempt to `api.anthropic.com` on port `8443`, with reason `port` (egress.jsonl:2). The order lookup and reply succeeded. The record does not show the attempted connection's purpose, payload, or any completed action through it.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The trace comes from the app process, has no rows, and can hide parameter values. Verify persisted return values with a read-only SQLite query. |
| stock.extra.toy.test | egress | Koodam egress span | The `egress_not_in_discovery` finding identifies one network attempt on port 443 (egress.jsonl:1). The span contains neither a request body nor a reply and does not establish a model API call. Check the discovery answer for this host and instrument its client to record calls. |
