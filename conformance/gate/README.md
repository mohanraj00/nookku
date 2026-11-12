# Gate cases

Each folder is one case of the gate run (SPEC.md section 7.15). `gate.json` is the gate file. `case.json` gives the subject, the records of each test that ran (`tests`) and the error of each test that did not run (`errors`). `expect_result.json` is the expected `result.json`. Its `gate_sha256` is the SHA-256 of `gate.json`, and the test puts it in. I wrote each expected file by hand.

`tests/test_gate.py` makes a sealed test folder for each test that ran: `manifest.json`, `findings.json`, `verdict.json`, `audit.json`, `relay.jsonl` and the script copy. It then writes the ledger rows, computes the result and compares it with `expect_result.json`. The test folder of the test `<name>` is `t-<name>`, and the gate id is `gate-case`.

| Case | It shows |
|---|---|
| `pass` | 2 tests that pass each check, one with a declared entry and one with a gate limit. The aggregate verdict is `pass`. |
| `fail` | A test with more `repeated_reply` findings than its gate limit, and a test with a turn that has no reply. The aggregate verdict is `fail`, with one reason for each test. |
| `missing_test` | A declared script that does not exist. The test did not run, so its only check is `missing_test`, and the aggregate verdict is `fail`. |
