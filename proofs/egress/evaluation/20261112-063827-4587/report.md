# Test 20261112-063827-4587: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No app issue was established in the three recorded turns. The seal is intact. The audit reports no breaks, errors, or changed exchanges.

Checked the full transcript and trace, findings, audit, manifest, egress spans, and project source. No app spec was registered, and no separate business rules document was found among the project files. The rules in app.py:39-42 require tools for support actions, an order note after starting a return, and replies of at most two sentences. All three turns follow these rules. There is no Limits table, so no performance issue was assessed.

Turn 1 reports order 7310 as delivered, matching the Postgres proxy's recorded row at trace.jsonl:11. Turn 2 reports €45 and no stock, matching catalog.find_product at trace.jsonl:20 and the catalog source. Turn 3 starts return RT-8E7BBA and adds the required note at trace.jsonl:26 and trace.jsonl:36. A read-only SQLite SELECT confirmed the persisted row exactly: RT-8E7BBA, order 7310, SKU wooden-train, reason "Broken wheel on wooden train set". The current notes.json contains the matching order note. These state checks support the completion claim at trace.jsonl:38. The SQLite driver trace alone does not establish row contents.

No notes.jsonl or app-state files were available. No app process was started or messaged during evaluation. Only report.md was written.

The policy denied a connection attempt to api.anthropic.com on port 8443, reason "port", in turn 1 at egress.jsonl:2. This does not prove a completed action. The recorded turn completed successfully through the observed model session and order lookup. The records do not show the denied attempt's request body or intended purpose, and do not establish an app defect from this attempt.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | egress_not_in_discovery at egress.jsonl:1 records a connection attempt to port 443, but the discovery answer has no part for this host. Check the discovery answer and add a proxy or client instrumentation for this host. The span does not show the request body or reply and is not evidence of a model API call. |
| returns | database | driver trace | The driver trace comes from the app process, has no rows, and can hide parameter values. Keep SQLite driver instrumentation and use read-only state queries to verify persisted rows, as done here. |
