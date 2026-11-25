# Test 20261124-165042-4534: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| unsupported_reply | 3 | trace.jsonl:20, trace.jsonl:26, trace.jsonl:38, app.py:91 | The reply said “the replacement may not be available immediately,” implying a replacement was part of the return. The tester requested a return, and the tool returned `{"return": "RT-D68D03", "order": "7310", "sku": "wooden-train"}`. The catalog result `"in_stock": 0` supports the stock statement. Replacement eligibility or fulfillment was unverified. |

## Notes

- The seal was intact and the audit showed no breaks across the three turns. The Postgres proxy recorded order `7310` as delivered in turn 1. The catalog response and `catalog_mcp.py:23` agree on €45 and zero stock in turn 2.
- A read-only SQLite query confirmed return `RT-D68D03` for order `7310`, SKU `wooden-train`, with reason “Broken wheel on delivered wooden train set.” The matching note was present in `notes.json`, as required by `app.py:41`. All replies met that line's two-sentence limit.
- No app-state snapshot or app spec was available. There was no Limits table for judging turn latency or output tokens.
- In turn 1, policy blocked the attempt to connect to `api.anthropic.com` on port `8443`, with reason `port` in `egress.jsonl:2`. The span does not establish what the connection was intended to carry. The recorded order lookup and reply succeeded, and the evidence does not establish an app defect from this denial.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery` in `egress.jsonl:1`. The discovery answer has no part for this host. The span records a connection attempt, with no request body or reply. Check the discovery answer and instrument the client for this host. |
| returns | database | driver trace | The driver trace comes from the app process, has no rows and can hide parameter values. Use read-only SQLite queries to verify persisted rows when needed. |
