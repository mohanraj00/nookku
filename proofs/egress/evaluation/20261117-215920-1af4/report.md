# Test 20261117-215920-1af4: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

No app issue was found in the three recorded turns. The seal is intact. The audit reports three exchanges and no breaks, errors or skipped checks.

Checked the transcript, findings, audit, manifest, egress records and all five Python source files. No app spec was registered, and no project rules document or Limits table was found. The rules in app.py require tool use, an order note after starting a return, and replies of at most two sentences. All three turns comply. Performance was recorded, but there is no Limits table against which to judge it.

Turn 1's reply, "Your order 7310 (1 wooden train set) has been delivered.", agrees with the Postgres proxy's returned row at trace.jsonl:11. Turn 2's €45 price and out-of-stock reply agree with catalog.find_product at trace.jsonl:20 and the product definition in catalog_mcp.py.

Turn 3 called shop.start_return with order "7310", SKU "wooden-train" and reason "Broken wheel on delivered wooden train set" at trace.jsonl:26, then notes.add_note at trace.jsonl:36. A read-only SQLite SELECT confirmed the stored row ["RT-5AA8DF", "7310", "wooden-train", "Broken wheel on delivered wooden train set"]. Reading notes.json confirmed the matching note, "Return RT-5AA8DF started for wooden train set (SKU wooden-train). Reason: broken wheel." These current-state checks support the reply at trace.jsonl:38. The SQLite driver spans alone do not establish stored values. No app-state files were available, so these local state checks are not sealed snapshots.

egress.jsonl:2 records a denied connection attempt to api.anthropic.com on port 8443, reason "port", with no turn assigned. The policy blocked the attempt. This does not prove a completed request or an app defect; the records do not show its request body, purpose or reply. The recorded user requests were fulfilled.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | The egress_not_in_discovery finding at egress.jsonl:1 records one connection attempt to a host absent from the discovery answer. Check that answer and add a proxy or client instrumentation for this host. The span records a network attempt, not the request body or reply, and does not establish a model API call. |
| returns | database | driver trace | The SQLite driver trace comes from the app process, has no rows and can hide parameter values. Keep driver instrumentation and verify stored values with read-only queries, as done here. A supported database proxy can record returned rows. |
