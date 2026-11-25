# Gate cases

Each folder is one case of the gate run (SPEC.md section 7.15). `gate.json` is the gate file. `case.json` gives the subject, the records of each test that ran (`tests`), the error of each test that did not run (`errors`) and the read of each proof file (`proofs`): its text or `null`, its modified time, the time of the read and the error of the read. A test can give `persona`, the text of its persona file, and the test puts the bytes in the copy of `inputs/`. A test can give `during`, the key `during` of each message of its script or `null`, `second_messages`, the key `second_messages` of its `findings.json`, and `outside_failures`, the key `outside_failures` of its `findings.json` (SPEC.md section 8.13). `expect_result.json` is the expected `result.json`. Its `gate_sha256` is the SHA-256 of `gate.json`, and the test puts it in. I wrote each expected file by hand.

`tests/test_gate.py` makes a sealed test folder for each test that ran: `manifest.json`, `findings.json`, `verdict.json`, `audit.json`, `relay.jsonl` and the script copy. If the case gives `tap`, the reply of each turn, it also writes `tap.jsonl`. `bases` gives the base tests of a replay check: the test makes a sealed folder with `relay.jsonl` and `tap.jsonl` for each base. The `entry` of the manifest and of the ledger row is the `entry` of the case. Both have an empty `policy`, `spec` and `config_sha256`. It then writes the ledger rows, computes the result and compares it with `expect_result.json`. The test folder of the test `<name>` is `t-<name>`, and the gate id is `gate-case`.

| Case | It shows |
|---|---|
| `pass` | 2 tests that pass each check, one with a declared entry and one with a gate limit. The aggregate verdict is `pass`. |
| `fail` | A test with more `repeated_reply` findings than its gate limit, and a test with a turn that has no reply. The aggregate verdict is `fail`, with one reason for each test. |
| `missing_test` | A declared script that does not exist. The test did not run, so its only check is `missing_test`, and the aggregate verdict is `fail`. |
| `replay_pass` | A replay check with the same replies as its base test, byte for byte. The count of changed turns is 0, so the check `changed_turns` passes. |
| `replay_changed` | A replay check where the reply of turn 2 changed and the limit is 0. The check `changed_turns` fails and names turn 2. |
| `replay_missing_base` | A replay check whose base test does not exist. The check `missing_base` fails, and the test has no check `changed_turns`. |
| `proof_pass` | A proof file that is 3600 seconds old, with `error_bound` 0.03. The limits are 86400 seconds and 0.05, so the proof file passes. |
| `proof_missing` | A proof file that the run cannot read. It fails with the reason `missing`, and it has no age and no value. |
| `proof_stale` | A proof file that is 3 days old. It fails with the reason `stale`. |
| `proof_above_limit` | A proof file with `error_bound` 0.08. It fails with the reason `above_limit`. |
| `second_message_pass` | A script whose message 2 has `during`, and a `findings.json` with a second message in turn 2. The check `second_message` passes. |
| `second_message_late` | The same script, and a `findings.json` with no second message: the entry got message 2 after the reply of turn 1. The check `second_message` fails, and the aggregate verdict is `fail`. |
| `inconclusive_provider_limit` | A test with 2 model calls that got the status 429, and no good call after them. The check `limits` fails, and the test is `inconclusive`, not `fail`. The aggregate verdict is `inconclusive`, with no reason, and the result has the key `inconclusive`. |
| `outside_failure_retried` | A test with 1 call that got the status 429, and a good call after it. The test keeps the verdict `pass`, and the result records the call in `outside_failures`. |
| `inconclusive_local_service` | A test with a backend that refused the connection in turn 2. Each check passes, and the test is `inconclusive` with the reason `local_service`. |
| `inconclusive_and_fail` | An inconclusive test and a test with a turn that has no reply. The aggregate verdict is `fail`, the reason names only the failed test, and the key `inconclusive` names the other test. |
| `persona_set` | A persona set of 3 personas: a new customer, a customer with a return and a customer who writes in short sentences. Each test has its persona in the result. The return persona has a replay check with a changed turn 2, so only that persona fails. |
