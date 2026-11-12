# Test 20261112-080836-d58f: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No app issue was established in the three recorded turns. The seal is intact, and audit.json reports no breaks or changed exchanges.

Checked the transcript, findings.json, audit.json, manifest.json, app.py, entry.py, toy_mcp.py, catalog_mcp.py, notes_mcp.py, and current saved state. No notes.jsonl or readable app-state files were present. The manifest names no app spec. The business instructions in app.py:39-41 require tool use, a note after starting a return, and replies of at most two sentences. All three turns comply. There is no Limits table, so no performance issue was assessed.

Turn 1's delivered status and item agree with the Postgres proxy result, trace.jsonl:11, which records `["7310", "delivered", "1 wooden train set"]`. Turn 2's €45 price and out-of-stock reply agree with catalog.find_product, trace.jsonl:18-22, and catalog_mcp.py's product data.

For turn 3, a read-only SQLite SELECT confirmed the saved row `('RT-1E1F29', '7310', 'wooden-train', 'Broken wheel')`. Current notes.json contains `"Return RT-1E1F29 started for wooden-train (1 unit). Reason: broken wheel."` for order `7310`. These agree with trace.jsonl:26, 34-38 and the required follow-up note. Current state is a separate check, not a claim that the driver trace recorded the inserted values.

The denied attempt in turn 1 was to api.anthropic.com port 8443, reason `port`, at egress.jsonl:2. The policy blocked the connection. This does not prove an action completed, and the record does not show its request body or purpose. The successful recorded order lookup and supported reply establish no app defect from this attempt. No policy change is recommended.

The connection to stock.extra.toy.test at egress.jsonl:1 is an undeclared egress host. Its span records a network attempt, not a request body or reply, and does not establish a model API call or an incorrect stock lookup.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery`, egress.jsonl:1, records one connection to port 443 with result `ok`; the discovery answer has no part with this host. Check the discovery answer and add a proxy or client instrumentation for this host. The span does not record the request body or reply. |
| returns | database | driver trace | The trace comes from the app process, has no rows, and can hide parameter values. CREATE and INSERT appear at trace.jsonl:30,32. Keep SQLite driver instrumentation and add a structured log of the committed return ID and fields so recorded writes can be checked against read-only state queries. |
