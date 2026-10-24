# Proof gaps

These results close the proof gaps of [issue #490](https://github.com/mohanraj00/nookku/issues/490).
The `nookku` field in each result gives the version of the checkout. The release proofs follow
the merge, as [the order of work](https://github.com/mohanraj00/nookku/issues/492) says.

The [tutorial method](../../scripts/proof_tutorial.py) records only the
[harness](../reference/glossary.md#harness) that ran. With
`--model`, it keeps the Claude Code version and omits Codex. With no model, it keeps no harness
version. The committed [run](../../proofs/tutorial/run.json) and
[output](../../proofs/tutorial/output.txt) come from the same `--model` run. The regression checks
in [test_proof_gaps.py](../../tests/test_proof_gaps.py) cover both modes.

The [plugin](../reference/glossary.md#plugin) load
[method](../../scripts/proof_plugin_load.py) passed each check in Claude Code and
Codex. Its [result](../../proofs/plugin/load.json) records the checkout version and the version
of each harness. The probe command now quotes its output path, so a scratch folder can have
spaces. The probe MCP server returns an error for an unknown request, so the resource list
request of Codex gets a reply. It still sends no reply to a notification.

The [egress method](../../scripts/proof_egress.py) passed again for `plugin-claude-code`. The
[result](../../proofs/egress/plugin-claude-code.json) records no changed app file, no refused
[relay](../reference/glossary.md#relay) row, 1 added guard row and 9 tool calls in the discovery.
These are the `E2_app_files_changed`,
`E2_relay_rows_refused`, `E2_guard_rows_added` and `E2_tool_calls` fields. Each required call has a
record, the [audit](../reference/glossary.md#audit) finds no
[break](../reference/glossary.md#break), and the
[seal](../reference/glossary.md#seal) is intact. The `versions` field gives the harness
versions and the packages of the toy shop. This run needs no change to the guard-row rule.
