# Test 20261031-082640-90a9: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

I found no issue of the app. The table has no rows.

The seal is intact: "Seal: intact. No record changed after the end of the test." The audit shows no break, no blocked call and no error. The verdict is `pass`.

The app spec is empty (`"spec": []` in `manifest.json`). Thus I took the business rules from the system prompt in `app.py:39-42`:

- "Use the tools for orders, products, returns and notes."
- "After you start a return, add a note to the order."
- "Answer in 2 sentences or fewer."

The spec has no `Persona`, `Boundaries`, `User goals` or `Limits` part. Thus I did not use the classes `tone`, `boundary`, `off_path` and `performance`.

What I checked for each turn:

1. Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The proxy row is `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply "Your order 7310 (1 wooden train set) has been delivered." agrees with the row.
2. Turn 2: `catalog.find_product` got `{"name": "wooden train"}` and gave `"price_eur": 45, "in_stock": 0` (trace.jsonl:18, trace.jsonl:20). The reply "costs €45, but it is currently out of stock" agrees with the result and with `catalog_mcp.py:22`.
3. Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel on wooden train set"}` and gave `"return": "RT-BCFE43"` (trace.jsonl:26). Then `notes.add_note` added a note to order 7310 (trace.jsonl:34, trace.jsonl:36). This obeys the rule "After you start a return, add a note to the order." The file `notes.json` has this note. The reply has 2 sentences. The statement about the stock comes from the tool result of turn 2.

What I could not check:

- I could not read the `returns` table of `returns.db`. The read-only query needed an approval that I did not get. The driver trace (trace.jsonl:32) has no rows and hides the parameter values. Thus the records cannot show that the row `RT-BCFE43` is in the database.
- I did not query the Postgres database `shop`. The proxy rows of turn 1 show the answer of the query.

Denied egress:

- Host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked this attempt. The model calls of turn 1 went through the Anthropic proxy, and the turn gave a correct reply. The records do not show which process made the attempt or why. No business rule or app record shows an app defect, so this is not an issue row.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery`: "stock.extra.toy.test: 1 span, and the egress answer has no part with this host" (egress.jsonl:1). The code of the app has no call to this host. Check the discovery answer, and add the part if the app uses this host. Then add a proxy or the OpenTelemetry instrumentation of the client for the host. The span records a network attempt, not the request body or the reply. |
| returns | database | driver trace | The driver trace comes from the app process. It has no rows and it can hide parameter values (trace.jsonl:30, trace.jsonl:32). No `driver_without_span` finding names this database. To see the rows, check the state with a read-only query after the test. |
