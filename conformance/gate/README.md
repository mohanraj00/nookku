# Gate cases

Each folder is one case of the gate run (SPEC.md section 7.15). `gate.json` is the gate file. `case.json` gives the subject, the records of each test that ran (`tests`) and the error of each test that did not run (`errors`). `expect_result.json` is the expected `result.json`. Its `gate_sha256` is the SHA-256 of `gate.json`, and the test puts it in. I wrote each expected file by hand.

`tests/test_gate.py` makes a sealed test folder for each test that ran: `manifest.json`, `findings.json`, `verdict.json`, `audit.json`, `relay.jsonl` and the script copy. If the case gives `tap`, the reply of each turn, it also writes `tap.jsonl`. `bases` gives the base tests of a replay check: the test makes a sealed folder with `relay.jsonl` and `tap.jsonl` for each base. The `entry` of the manifest and of the ledger row is the `entry` of the case. Both have an empty `policy`, `spec` and `config_sha256`. It then writes the ledger rows, computes the result and compares it with `expect_result.json`. The test folder of the test `<name>` is `t-<name>`, and the gate id is `gate-case`.

| Case | It shows |
|---|---|
| `pass` | 2 tests that pass each check, one with a declared entry and one with a gate limit. The aggregate verdict is `pass`. |
| `fail` | A test with more `repeated_reply` findings than its gate limit, and a test with a turn that has no reply. The aggregate verdict is `fail`, with one reason for each test. |
| `missing_test` | A declared script that does not exist. The test did not run, so its only check is `missing_test`, and the aggregate verdict is `fail`. |
| `replay_pass` | A replay check with the same replies as its base test, byte for byte. The count of changed turns is 0, so the check `changed_turns` passes. |
| `replay_changed` | A replay check where the reply of turn 2 changed and the limit is 0. The check `changed_turns` fails and names turn 2. |
| `replay_missing_base` | A replay check whose base test does not exist. The check `missing_base` fails, and the test has no check `changed_turns`. |
