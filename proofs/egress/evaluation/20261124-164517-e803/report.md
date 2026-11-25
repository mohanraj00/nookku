# Test 20261124-164517-e803: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No app issues were found in the three recorded turns. The seal was intact and the relay audit reported no breaks.

- Turn 1 reported order `7310` as delivered with `1 wooden train set`, matching the Postgres proxy row at `trace.jsonl:11`. I used the recorded query result for the order and did not query live Postgres separately.
- Turn 2 reported €45 and no stock, matching `"price_eur": 45, "in_stock": 0` at `trace.jsonl:20` and the catalog source.
- Turn 3 started the return and added an order note, as required by `app.py:41`. A read-only SQLite query found `RT-4B57A4|7310|wooden-train|Broken wheel`, and `notes.json` contained the order note recorded at `trace.jsonl:36`. All three replies met the two-sentence rule in `app.py:41`.
- The test had no app spec or performance limits to apply, and no `app-state/` snapshot. The recorded turn times were 4.253, 4.215 and 6.698 seconds. The model sessions produced 81, 81 and 279 output tokens, respectively.
- `egress_denied` at `egress.jsonl:2` records `connect api.anthropic.com port 8443: denied (port)`. No turn was assigned. The policy blocked the connection attempt. The record does not establish what request would have been sent or show a failed tester action attributable to the denial.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery` at `egress.jsonl:1` records a connection attempt to a host absent from the discovery answer. The span has neither the request body nor the reply. Check the discovery answer and add a proxy or client instrumentation for this host. |
| returns | database | driver trace | The SQLite driver trace comes from the app process, has no rows and can hide parameter values. Use a read-only SQLite query to verify persisted returns. |
