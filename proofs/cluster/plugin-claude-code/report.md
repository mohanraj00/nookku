# Test 20261105-113654-8811: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|

## Notes

- I found no issue. The app is a thin entry (`service_entry.py:20-25`) that forwards each message to the backend `toy-shop` and returns its `reply`. The tool-based checks do not apply: the test has no model session and no tool calls.
- I did not run `nookku transcript`. The transcript tool was not granted, so I read `relay.jsonl`, `backend.jsonl`, `tap.jsonl`, `findings.json`, `audit.json`, `performance.json`, `manifest.json` and `egress.jsonl` directly. The audit has no break, and the 3 turns match the 3 backend calls. I did not recompute the hashes in `seal.json`. I saw no sign that a file changed.
- The test has no app spec (`spec: []`) and no rules document. The project holds only `service_entry.py`. I could not check business rules, `Persona`, `Boundaries` or `User goals`. So I report no `business_rule`, `tone`, `boundary` or `off_path` row.
- Turn 1 (`backend.jsonl:1`): the tester wrote "the mug i ordered came with a crack in the handle". The app replied "Which item is this about: the mug or the teapot?" The tester had already named the mug, so the question looks redundant. No rule or spec shows it is wrong. It may be worth a look by the owner of the backend.
- Turn 2: the reply is "Damaged items: full refund. Change of mind: 30 days." I could not check it against a rules source.
- Turn 3: "do you ship to delhi?" got "We ship to Chennai and Pune." The reply implies no, without saying it. I could not check it against a rules source.
- Limits: the spec has no `Limits` table, so I report no `performance` issue. Turn times were 0.017 s, 0.007 s and 0.010 s. Token counts are `not known`.
- `egress_denied` (`egress.jsonl:17`): the connection `CONNECT example.com:22` was denied with reason `port`, status 403. It happened at 11:37:00.65Z, between turn 2 and turn 3, in no turn window. The code of the app (`service_entry.py`) makes no call to `example.com`. The records do not show who made the call; it may have come from the tester session. The policy blocked the attempt. This is not an app issue. The record cannot show the source process.
- `egress_not_in_discovery` (`egress.jsonl:16`): a `GET example.com:80` returned 200. See Coverage.
- The seal shows no change after the end of the test.

## Tester notes

The tester wrote no note.

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| example.com | egress | Koodam egress span | Finding `egress_not_in_discovery`, `egress.jsonl:16` (2 spans: GET port 80 allowed, CONNECT port 22 denied at `egress.jsonl:17`). No turn. Check the discovery answer and add a proxy or client instrumentation for this host. The span records a network attempt, not the request body or the reply. |
