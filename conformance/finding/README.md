# Finding record cases

Each file is one case of the reader of a finding record (SPEC.md section 10). `record` is the record. `expect.problem` is the problem that the reader gives, or `null` for a valid record. `expect.schema` is `true` if the record agrees with the JSON Schema of `src/nookku/finding_record.schema.json`. The schema checks the form only, so a record with a seal digest that does not match agrees with the schema. I wrote each expectation by hand. `tests/test_finding_record.py` reads each case, and checks the reader and the schema.

| Case | It shows |
|---|---|
| `valid_answer_key_mismatch` | A mismatch with the answer key that a person adjudicated as `agent_wrong`: the key gives 112, and the reply gives 120. |
| `valid_issue_row` | An issue row of a person, with a turn. `expected` and `observed` are `null`. |
| `valid_model_issue_row` | A model row with no turn. The author is `null`, and the author type is `model`. |
| `valid_gate_record` | A record of a test of a gate run, with the gate id, the name of the test and the SHA-256 of `result.json`. |
| `valid_unknown_field` | A field that version 1 does not have, in the record and in `expected`. The reader ignores each one. |
| `valid_newer_minor_version` | A record of version `1.7` with a field that the reader does not know. The reader reads it. |
| `missing_field` | A record with no `subject`. |
| `missing_key_of_an_object` | A `script` with no key `sha256`. An object of a record has each of its keys, also a key with the value `null`. |
| `unknown_major_version` | A record of version `2.0`. The reader refuses it. |
| `seal_digest_mismatch` | `seal.sha256` is not the SHA-256 of `seal.text`. |
| `seal_file_not_covered` | `seal.files` gives a SHA-256 of `findings.json` that the seal text does not have. |
| `turn_not_in_script` | `turn.input` is not the message of `script` at `turn.number`. |
| `mismatch_with_model_author` | A mismatch with the author type `model`. Only a person adjudicates a mismatch. |
