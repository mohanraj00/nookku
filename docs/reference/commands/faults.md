# `nookku faults`

Release: nookku 0.7.0.

```text
nookku faults [--cases PATH] [--json]
```

Run each check of the [trace](../glossary.md#trace) on its seeded faults, with no model ([ADR 0002](../../contributing/adr/0002-seeded-faults-personas-answer-keys-verifiers.md#nookku-faults), [#546](https://github.com/mohanraj00/nookku/issues/546)). A seeded fault is a trace case of the conformance suite that expects a [finding](../glossary.md#findings) of a check. The file `faults.json` of the case names the check and the turn of each fault. The command copies each case to a temporary folder and builds its trace. A fault is found if the trace gives a finding of its check in its turn. The report has one line for each fault, then the count of faults found and the count of checks with a fault. The package does not hold the conformance suite, so run the command in a checkout of the repo.

| Flag | Default | Meaning |
|---|---|---|
| `--cases PATH` | `conformance/trace` | The folder of the trace cases. |
| `--json` | off | Print the report as JSON: `nookku`, `cases`, `checks`, `faults` (each with `case`, `check`, `turn`, `found` and `error`), `missed`, `unseeded` and `ok`. |

| Exit code | Meaning |
|---|---|
| 0 | Each fault is found, and each check of SPEC.md section 8.6 has a fault. |
| 1 | A check missed a fault, or a check has no fault. |
| 2 | The folder has no case with `faults.json`, or a `faults.json` is not valid. |

## Example

In the root of this repo, which holds the conformance cases. The output has one line for each seeded fault. This is its start and its end. The counts come from the trace cases in [conformance/trace](../../../conformance/trace) of this checkout, with the method of [faults.py](../../../src/nookku/faults.py). The release step records the result of each release, for example [faults-0.6.2.json](../../../proofs/release/faults-0.6.2.json) (97 of 97 faults in 49 cases).

```bash
nookku faults
```

```text
found  answer_key_mismatch (turn 3) in answer_key
found  answer_key_mismatch (turn 4) in answer_key
...
found  version_untested (no turn) in untested_versions
Nookku 0.6.2: 108 of 108 seeded faults found in 52 trace cases. 33 of 33 checks have a seeded fault.
```
