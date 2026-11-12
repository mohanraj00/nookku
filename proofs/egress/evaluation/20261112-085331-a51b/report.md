# Test 20261112-085331-a51b: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

I found no issue of the app.

What I checked:

- Seal: intact. No record changed after the end of the test. `audit.json` has no break, no error and no skipped turn (3 turns, 3 exchanges, 0 blocked calls).
- Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The Postgres proxy recorded the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply "Your order 7310 (1 wooden train set) has been delivered." agrees with it.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}` and returned `"price_eur": 45, "in_stock": 0` (trace.jsonl:18, trace.jsonl:20). The reply "costs €45, but it is currently out of stock" agrees with it and with `catalog_mcp.py:23`.
- Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel on delivered wooden train set"}` and returned `"return": "RT-5EBEC0"` (trace.jsonl:26). Then `notes.add_note` got the order 7310 and the text "Return RT-5EBEC0 started for wooden train set (SKU wooden-train). Reason: broken wheel." (trace.jsonl:34, trace.jsonl:36). This agrees with the rule "After you start a return, add a note to the order." (`app.py:41`). The reply names the same return reference.
- State: `notes.json` holds 1 note for order 7310 with the text of trace.jsonl:34. `returns.db` holds the row `RT-5EBEC0`, `7310`, `wooden-train`, `Broken wheel on delivered wooden train set`. The reply of turn 3 agrees with both.
- Rule "Answer in 2 sentences or fewer." (`app.py:41`): the replies have 1, 2 and 2 sentences.
- The test has no app spec (`"spec": []` in `manifest.json`). The business rules are thus only those of the system prompt (`app.py:39-42`). I did not use the classes `tone`, `boundary` and `off_path`, and with no `Limits` table I did not judge `performance`. The turns took 2.371, 2.107 and 4.923 seconds, with 81, 138 and 303 output tokens.
- `egress_denied`: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked a connect attempt. No model call failed (`model_api_error` 0, `agent_error` 0), and all 7 model calls of the session passed the proxy with a reply. No file of the app names port 8443. The records cannot show which code made the attempt or what it wanted to send. No rule or reply proves an app defect, so this is not an issue row.
- `model_api.jsonl:1` is a `HEAD /api/hello` call with no harness (the 1 `other_calls` of the manifest). It is a connection check of the client, not a model call.

What I could not check:

- I read `returns.db` with `strings`, not with a SELECT query: the shell needed an approval for `sqlite3`. The file shows 1 row, but I could not count the rows with a query.
- The INSERT of turn 3 is a driver trace (trace.jsonl:32). It has no parameter values, so the trace alone does not show the row. The file state above shows it.
- I did not query the Postgres database `shop`. The proxy recorded the row of the one SELECT, and the app made no write to it.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| returns | database | driver trace | The driver trace comes from the app process, has no rows and can hide parameter values (trace.jsonl:30, trace.jsonl:32 have `"parameters": null`). The trace has the queries of the database, and no `driver_without_span` finding names it. To see the values, add a log line for each write of `start_return`. |
| stock.extra.toy.test | egress | Koodam egress span | `egress_not_in_discovery`: 1 span, and the egress answer has no part with this host (egress.jsonl:1, connect port 443, result `ok`). The match is by host, and the finding has no turn. No file of the app names this host. Check the discovery answer, and add a proxy or the instrumentation of the client for this host. The span records a network attempt, not the request body or the reply, and it is not a call of a model API. |
