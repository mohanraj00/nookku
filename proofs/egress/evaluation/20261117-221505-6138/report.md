# Test 20261117-221505-6138: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 3 | trace.jsonl:38; trace.jsonl:26,36; app.py:99-118 | The reply promises, "You'll receive further instructions for sending the item back." The return tool returns only the return ID, order and SKU, and the notes tool confirms a note. Neither result nor the app rules support a future delivery of instructions. The return implementation only saves a SQLite record. |

## Notes

The seal is intact. The audit reports no breaks, errors or changed exchanges. Reviewed all three turns, findings, manifest egress coverage, and the app, entry point and MCP server code. No separate app spec or Limits table was supplied or found, so no performance issue is assessed. All replies meet the app's two-sentence rule in app.py:39-42.

Turn 1's order status is supported by the Postgres proxy's returned row, `["7310", "delivered", "1 wooden train set"]`, at trace.jsonl:11. Turn 2's price and stock match the catalog result at trace.jsonl:20 and the product data in catalog_mcp.py.

Checked current persisted state with `sqlite3 -readonly returns.db 'SELECT id, order_id, sku, reason FROM returns;'`. It returned `RT-57B305|7310|wooden-train|Broken wheel on delivered wooden train set`. Read notes.json, which contains the matching order note. These current files agree with the return and note tool results at trace.jsonl:26,36. They are current project state, not sealed snapshots. No app-state files or tester notes file were found. A live Postgres query was not performed; the sealed proxy record provides the order row returned during the test.

Turn 1 has an egress denial for `api.anthropic.com`, port 8443, reason `port`, at egress.jsonl:2. The policy blocked an attempt; this does not establish a completed request. The records do not show its request body or intended purpose. The turn completed with a supported order reply, and no rule or trace establishes an app defect from this denial alone.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process, has no rows and can hide parameter values. CREATE and INSERT spans appear at trace.jsonl:30,32; the read-only state check confirms the saved return. Retain driver instrumentation and use read-only state checks to verify persisted values. |
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery` at egress.jsonl:1 reports one span for a host absent from the discovery answer, with no turn assigned. Check the discovery answer and add a proxy or client instrumentation for this host. The span records a network attempt, not its request body or reply, and does not establish a model API call. |
