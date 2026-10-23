# Codex tool-result ids

I tested the Codex version in [the data](codex-call-id.json), with [this method](../../scripts/spike_codex_call_id.py). The method runs a toy shop shell test in an isolated project. It uses the project-proof Codex home of the main checkout. It stores ids, names and source lines. It stores no model answer or telemetry output text.

The `OTEL_* only` run completes, but gives no tool-result log. The native `otel.exporter` run gives `codex.tool_result` logs with `call_id`. The `native_overrides` field records the exporter configuration. The result is a tested bound for this Codex version.

The native run has separate id paths:

| Log tool | Log field | Rollout match |
|---|---|---|
| `exec` | `call_id` | `response_item` of type `custom_tool_call`, field `call_id` |
| `exec_command` | `call_id` | `event_msg.item_completed` of type `CommandExecution`, field `item.id` |

The outer `exec` call and the command inside it have different ids. A match must use the id of the correct layer. `tool_result_logs` gives the matching source lines. `checks` verifies each result and each call. The command name alone cannot distinguish the calls of this run.

The trace currently reads completed command items. It could match their result logs by `item.id`. An outer `exec` result needs its response-item call too. This spike changes no reader or record rule. A later implementation must test both layers, also for a result with an unknown id.

This run tests shell calls only. It does not establish the id rule for an MCP call or a dynamic tool call.
