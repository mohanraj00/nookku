# Test 20261117-153151-458d: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- Seal: intact. The audit shows no break (`breaks: []`), 3 turns and 3 exchanges, so the turn numbers of the transcript and of `relay.jsonl` agree.
- I found no issue of the app.
- The business rules come from the system prompt in `app.py:38-41` ("Use the tools for orders, products, returns and notes. After you start a return, add a note to the order. Answer in 2 sentences or fewer.") and the tool docstrings. The manifest has no app spec (`spec: []`), and `verdict.limits` is empty. Thus I used no `tone`, `boundary`, `off_path` or `performance` class.
- Turn 1: `shop.lookup_order` got `{"order": "7310"}` (trace.jsonl:6). The Postgres proxy recorded the row `["7310", "delivered", "1 wooden train set"]` (trace.jsonl:11). The reply "Your order 7310 (1 wooden train set) has been delivered." agrees with the row.
- Turn 2: `catalog.find_product` got `{"name": "wooden train"}`. The result was `price_eur: 45, in_stock: 0` (trace.jsonl:18, trace.jsonl:20), and it agrees with `catalog_mcp.py:22`. The reply "costs €45, but it is currently out of stock" agrees.
- Turn 3: `shop.start_return` got `{"order": "7310", "sku": "wooden-train", "reason": "Broken wheel"}` and returned `RT-B43FC9` (trace.jsonl:26). Then `notes.add_note` ran for order 7310 (trace.jsonl:34, trace.jsonl:36), as the rule "After you start a return, add a note to the order" needs. `notes.json` in the project holds that one note. The reply has 2 sentences, so it keeps the 2-sentence rule. The return ID and the out-of-stock fact come from tool results of turns 2 and 3.
- A small point, not an issue: the note says "wheel arrived broken". The tester said only that the train set "has a broken wheel", and did not say when it broke. The note is internal, so I did not count it as a reply issue.
- I could not check the `returns` SQLite table (`returns.db`). The read-only query needed an approval, and it was not run. The driver trace shows only the `CREATE` and the `INSERT INTO returns VALUES (?, ?, ?, ?)` with no parameters (trace.jsonl:30, trace.jsonl:32). The records cannot show that the row `RT-B43FC9 / 7310 / wooden-train / Broken wheel` exists.
- `egress_denied`: host `api.anthropic.com`, port 8443, reason `port`, egress.jsonl:2, turn 1. The policy blocked an attempt. Turn 1 still finished with a reply from the model (trace.jsonl:14-15, model `claude-haiku-5-5`), so I found no app defect. The records do not show which process made the attempt, or what it would have sent.
- Performance: no `Limits` table, so I checked no limit. For information only: turn 1 took 2.372 s with 81 output tokens, turn 2 took 2.224 s with 81, and turn 3 took 3.998 s with 288.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| stock.extra.toy.test | egress | Koodam egress span | Finding `egress_not_in_discovery` (egress.jsonl:1): a `connect` to port 443, result `ok`, at 10:01:56, and the egress answer has no part with this host. The app code (`app.py`, `catalog_mcp.py`, `notes_mcp.py`) does not name this host. Check the discovery answer and add the part if the app uses it. Then add a proxy or the client instrumentation for the host. The span records a network attempt, not the request body or the reply. |
| returns | database | driver trace | The driver trace comes from the app process (the `sqlite3` OpenTelemetry instrumentation). It has no rows and can hide parameter values: here the `INSERT` shows no parameters. Check the state with a read-only query. No `driver_without_span` finding names this database. |
