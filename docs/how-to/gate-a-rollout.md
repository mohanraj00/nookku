# Gate a rollout on a gate result

Release: nookku 0.6.2.

A rollout controller moves traffic to a new version of an app only if a check passes. A [gate run](gate-a-release.md) gives this check: one sealed result with an aggregate verdict and the subject digest of the version. This page names the files and the fields that a controller reads. [SPEC.md section 7.15](../../SPEC.md#715-gate-run) has the rules.

Nookku owns the format of the result. The controller only reads files, so this page does not depend on one platform. An analysis step of a rollout tool, a CI job and a script use the same steps.

## The files that a controller reads

| File | Where | What it is |
|---|---|---|
| `result.json` | The gate folder, `.nookku/gates/<gate id>/` | The result. It is plain JSON. |
| The copy of the [seal](../reference/glossary.md#seal) | `$NOOKKU_HOME/seals/<gate id>.json` | The SHA-256 of each file of the gate folder, outside the gate folder. |

The controller reads these fields of `result.json`:

| Field | Type | Use |
|---|---|---|
| `verdict` | string | `pass`, `fail` or `inconclusive`. Promote only for `pass`. An `inconclusive` result has a test with a call that failed for a cause outside the app, for example a provider limit. Run the gate again. |
| `subject` | string | The digest that the caller gave to `nookku gate run --subject`. Compare it with the digest of the new version. |
| `gate` | string | The gate id. It names the gate folder and the copy of the seal. |
| `reasons` | list | For a `fail`: one object `{"test", "check"}` for each check of a test that fails, and one object `{"proof", "check"}` for each failure of a proof file. Show them to the person who owns the rollout. |
| `problems` | list of strings | For a `fail`: each problem of the ledger of the run. |

The controller reads this field of the copy of the seal:

| Field | Type | Use |
|---|---|---|
| `files["result.json"]` | string | The SHA-256 of `result.json` at the time of the seal. |

## The rule of the controller

Promote the new version only if each of these is true. Else stop the rollout.

1. `result.json` is a JSON object.
2. The SHA-256 of `result.json` is `files["result.json"]` of the copy of the seal.
3. `subject` is the digest of the new version. The subject is only the text that the caller gave, so the controller must compute the digest of the new version itself.
4. `verdict` is the string `pass`.

Step 2 shows only that `result.json` did not change after the seal. It does not check the [test folders](../reference/glossary.md#test-folder). For the full check, run `nookku gate verify <gate id>` where the gate folder, the tests folder and the copies of the seals are. It exits with 0 if the result can be used and its verdict is `pass`, with 1 for `fail`, and with 2 if the result cannot be used. A controller that can run a command uses this exit code in place of steps 1, 2 and 4, and still does step 3.

Keep the copies of the seals in a place that the tested app and the model cannot write. In CI, set `NOOKKU_HOME` to such a folder.

## The example

[examples/rollout-gate/](../../examples/rollout-gate/) has a toy rollout with no model:

- `agent_v1.py` and `agent_v2.py` are 2 versions of a toy shop agent. Version 2 has a planted defect: in each turn, it asks the stock service for a product that the service does not know, and gets status 503. The replies of the 2 versions are the same, so a compare of the replies does not find the defect.
- `gate.json` declares 1 [scripted test](../reference/glossary.md#scripted-test) with the limit `backend_error: 0`.
- `controller.py` is the rule of this page in 1 function, `decide`. It uses only the standard library of Python.

To gate one version, set `entry` of the project to the version, and run the gate with the digest of the version as the subject:

```bash
nookku gate run gate.json --subject "sha256:<the SHA-256 of the agent file>"
python controller.py --gate .nookku/gates/<gate id> --seal "$NOOKKU_HOME/seals/<gate id>.json" --subject "sha256:<the SHA-256 of the agent file>"
```

`controller.py` prints its decision as JSON, and exits with 0 for `promote` and with 1 for `stop`.

## The proof

[scripts/proof_rollout_gate.py](../../scripts/proof_rollout_gate.py) runs the example for the 2 versions ([data](../../proofs/rollout-gate/results.json)). [results.md](../results.md#a-rollout-gate) gives the result.

## Limits

- The example is a toy. It does not move traffic. A real controller has its own way to read a file and to stop a rollout.
- The subject is text. Nookku does not check that the tested app is the thing with this digest. The process that starts the gate run must start the app from the same digest.
- A gate run uses scripted tests and deterministic checks only. A model judgment does not change its verdict ([SPEC.md section 7.15](../../SPEC.md#715-gate-run)).
- An adapter for one rollout tool, for example an analysis step that runs the 2 commands, is not a part of Nookku. Its test belongs to the project of the adapter, and it pins a released Nookku version.
