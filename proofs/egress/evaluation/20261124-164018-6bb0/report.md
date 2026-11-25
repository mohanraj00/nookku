# Test 20261124-164018-6bb0: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- The seal was intact, and the relay audit showed no breaks across the three turns. I reviewed the transcript, findings, discovery manifest, and app source. No app-state snapshot files were available.
- I found no app issue. Order 7310 was reported as delivered, matching the Postgres proxy row in `trace.jsonl:11`. I used that recorded row for the order check without a separate live Postgres query. The €45 price and out-of-stock answer match `trace.jsonl:20` and `catalog_mcp.py:23`.
- The read-only SQLite query confirmed return `RT-3937DA` for order `7310`, SKU `wooden-train`, with reason `Broken wheel on delivered wooden train set`. The persisted entry in `notes.json` matches the note in `trace.jsonl:36` and fulfills the rule in `app.py:41`.
- The test had no app spec with a Limits table. The recorded durations were 4.297, 4.066, and 6.934 seconds, and the combined model-session output counts were 81, 81, and 301 tokens.
- In turn 1, policy denied a connection attempt to `api.anthropic.com:8443` because of the port rule (`egress.jsonl:2`). The span establishes that the attempt was blocked. The records do not identify the operation it would have carried. The order lookup and reply succeeded.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| `stock.extra.toy.test` | egress | Koodam egress span | `egress_not_in_discovery` in `egress.jsonl:1` records one network attempt and provides no request body or reply. Check the discovery answer for this host and instrument its client with OpenTelemetry. |
| returns | database | driver trace | The SQLite driver trace comes from the app process, has no result rows, and can hide parameter values. Use a read-only SQLite query to verify persisted values. |
