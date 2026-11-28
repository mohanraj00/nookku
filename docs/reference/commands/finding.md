# `nookku finding`

Release: nookku 0.6.1.

```text
nookku finding export [TEST] --subject DIGEST [--model-rows] [--root PATH] [--tests-dir PATH]
nookku finding export --gate GATE [--model-rows] [--root PATH] [--tests-dir PATH]
nookku finding check FILE [--json]
nookku finding schema
```

Export each confirmed defect of a test, or of a gate run, as a [finding record](../glossary.md#finding-record): one JSON object that another tool reads with no other file ([SPEC.md section 10](../../../SPEC.md#10-finding-record)). [Import a finding record](../../how-to/import-a-finding-record.md) shows the steps.

- `export` prints one record on each line. A record comes from a mismatch with the answer key that [`nookku adjudicate`](adjudicate.md) gave the outcome `agent_wrong`, or from an issue row of a person of [`nookku evaluation add`](evaluation.md).
- `export` prints no record if the [seal](../glossary.md#seal) of a test is not intact, or if a record of the [test folder](../glossary.md#test-folder) is not valid.
- `check` checks each line of a file of records: the fields, the version and the seal digest.
- `schema` prints the JSON Schema of a record.
- The command reads, and it writes no file. The [relay](../glossary.md#relay) lets the model run it.

```text
$ nookku finding export 20261120-101500-a1b2 --subject sha256:ab12cd34 > findings.jsonl
nookku: 1 finding records.
$ nookku finding check findings.jsonl
line 1: ok 20261120-101500-a1b2/answer_key_mismatch/2
1 records, 0 not valid.
```

| Flag | Default | Meaning |
|---|---|---|
| `COMMAND` | required | `export`, `check` or `schema`. |

The flags of `export` and `check`:

- `TEST`, for `export` only: the test id, or the path of the test folder. The default is the latest test.
- `--subject DIGEST`, for `export` of a test only: the digest of the tested thing, 1 to 512 characters. It is required. Nookku does not interpret it.
- `--gate GATE`, for `export` only: a gate id or a gate folder. The command exports each test of the gate run, with the subject of the gate run. It takes no `TEST` and no `--subject`.
- `--model-rows`, for `export` only: also export the model rows of `evaluation.json`. A model row is a model judgment that no person confirmed, and its record has the author type `model`.
- `--root PATH`, for `export` only: the project. The default is the current folder.
- `--tests-dir PATH`, for `export` only: the [tests folder](../cli.md#the-tests-folder). The default is `$NOOKKU_TESTS_DIR`, else `.nookku/tests`.
- `FILE`, for `check` only: a JSONL file of records, or `-` for the standard input.
- `--json`, for `check` only: print `{"records": ..., "valid": ..., "lines": ...}`.

| Command | Exit code | Meaning |
|---|---|---|
| `export` | 0 | Each record was printed. A test with no confirmed defect prints no record. |
| | 2 | No record was printed: no test or gate folder, no subject, a seal that is not intact, or a record of the test folder that is not valid. |
| `check` | 0 | Each line is a valid record. |
| | 1 | A line is not a valid record. The output gives the problem of each line. |
| | 2 | The file cannot be read as UTF-8. |
| `schema` | 0 | The schema was printed. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku finding export 20261127-194213-41bc --subject sha256:ab12cd34 > findings.jsonl && nookku finding check findings.jsonl
```

```text
nookku: 1 finding records.
line 1: ok 20261127-194213-41bc/issue_row/1
1 records, 0 not valid.
```
