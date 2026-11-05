# Test 20261105-174737-003f: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No app issue was found in the three recorded turns. The seal is intact, and audit.json reports no breaks or errors.

Checked the full transcript and trace, findings.json, audit.json, manifest.json, all five app source files, notes.json, and the returns database using a read-only SQLite connection. No notes.jsonl or app-state files were available. The manifest names no app spec, and no project rules document was found. The rules in app.py:39–41 require tools, an order note after starting a return, and replies of at most two sentences. All three turns comply.

Turn 1 reports order 7310 as delivered, matching the Postgres proxy answer at trace.jsonl:11. Turn 2 reports €45 and no stock, matching trace.jsonl:18–20 and catalog_mcp.py. Turn 3 starts return RT-815380 and adds the required note, matching trace.jsonl:26 and trace.jsonl:34–36. A read-only SELECT confirmed the stored return row as ["RT-815380", "7310", "wooden-train", "Broken wheel"]. notes.json contains the matching order note. These current local files are independent state checks, not sealed app-state snapshots. The Postgres rows were checked through the recorded proxy answer rather than a fresh database query.

No Limits table was supplied, so no performance issue is assessed. Recorded turn durations were 2.8, 3.779, and 5.466 seconds; combined model output tokens were 100, 96, and 278.

egress.jsonl:2 records a denied connection attempt to api.anthropic.com port 8443 in turn 1, with reason "port". The policy blocked the attempt; this does not prove completion. The records do not show its request body, reply, or purpose. Turn 1 nevertheless completed with a supported answer, and no rule or trace establishes an app defect from this attempt.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | egress_not_in_discovery at egress.jsonl:1 records one span for a host absent from the discovery answer, with no turn assigned. Check the discovery answer and add a proxy or client instrumentation for this host. The span records a network attempt, not its request body or reply, and does not establish a model API call. |
| returns | database | driver trace | The driver trace comes from the app process, has no rows, and can hide parameter values. Queries are present at trace.jsonl:30 and trace.jsonl:32. Keep read-only state verification for SQLite, or log the committed return ID and fields to make persisted outcomes observable. |
