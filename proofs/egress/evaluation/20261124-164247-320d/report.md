# Test 20261124-164247-320d: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- No app issues found in the three recorded turns. The seal was intact and the audit reported no breaks between the tester and the app.
- The Postgres proxy returned `["7310", "delivered", "1 wooden train set"]` in turn 1 (`trace.jsonl:11`). The catalog returned `"price_eur": 45` and `"in_stock": 0` in turn 2 (`trace.jsonl:20`), consistent with the catalog source and the reply.
- In turn 3 the app started the return, then added the required support note (`app.py:41`, `trace.jsonl:26`, `trace.jsonl:36`). A read-only SQLite query confirmed return `RT-B5B886` for order `7310`, SKU `wooden-train`, with reason `Broken wheel on delivered wooden train set`. The saved `notes.json` entry matched the note in the trace. Each reply met the two-sentence rule.
- No app spec with a Limits table was available, so there were no performance thresholds to apply. The sealed proxy row was the source for the order state during the test.
- In turn 1, the egress policy blocked a connection attempt to `api.anthropic.com:8443` for reason `port` (`egress.jsonl:2`). The record cannot show the intended request or its purpose. The order lookup succeeded and the reply matched the result, so the denied attempt supplies no evidence of an app defect.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery` at `egress.jsonl:1`. Check the discovery answer for this host and route its client through a recording proxy. The span records a network attempt only. The request body and reply are unavailable. |
| returns | database | driver trace | The driver trace comes from the app process, contains no rows and can hide parameter values. Use a read-only SQLite query to verify persisted values. |
