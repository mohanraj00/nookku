# Gate a release with a set of tests

A gate run runs a declared set of [scripted tests](../reference/glossary.md#scripted-test) and writes one sealed result. The result has the verdict of each test, one aggregate verdict and the subject digest that you give, for example the digest of the image that you test. [SPEC.md section 7.15](../../SPEC.md#715-gate-run) gives the format and each check.

## Write the gate file

Put the gate file and the scripts in the project. The paths are relative to the folder of the gate file.

```json
{
  "v": 1,
  "tests": [
    {"name": "refund", "script": "scripts/refund.jsonl", "entry": "shop"},
    {"name": "price", "script": "scripts/price.jsonl", "limits": {"agent_error": 0}}
  ]
}
```

- `name` names the test in the result.
- `script` is a script of `nookku run --script` ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)). `nookku script save` writes one from a test.
- `entry` is optional, a name of the config key `entries`.
- `limits` is optional. It adds limits to the `Verdict` table of the app spec. Only the checks of the [trace](../reference/glossary.md#trace) can have a limit. A model issue class, for example `tone`, cannot.

## Run the set

1. Register the egress answer of the app, as for each test (`nookku register`). The gate run uses one answer for all of its tests.
2. Run the gate with the digest of the thing that you test:

   ```bash
   nookku gate run gates/gate.json --subject "sha256:ab12cd34"
   ```

The command prints the lines of each test, one line for each test and the aggregate verdict. It exits with 0 if the aggregate verdict is `pass`, with 1 if it is `fail`, and with 2 if no test ran.

The result folder is `.nookku/gates/<gate id>/`. In CI, set `NOOKKU_HOME` to a folder that the job can write, because the copy of the [seal](../reference/glossary.md#seal) goes there.

## Read the result in a CI job or a rollout controller

`result.json` is plain JSON, so a reader needs no Nookku process. Do these steps:

1. Read the aggregate verdict and the subject:

   ```bash
   jq -r '.verdict, .subject' .nookku/gates/<gate id>/result.json
   ```

2. Compare the subject with the digest that you expect. Do not trust the subject alone. It is only the text that the caller gave.
3. Compare the SHA-256 of `result.json` with the copy of the seal:

   ```bash
   shasum -a 256 .nookku/gates/<gate id>/result.json
   jq -r '.files["result.json"]' "$NOOKKU_HOME/seals/<gate id>.json"
   ```

Step 3 shows only that `result.json` did not change. It does not check the [test folders](../reference/glossary.md#test-folder). For a full check, run `nookku gate verify` on a machine that has the gate folder, the tests folder and the copies of the seals:

```bash
nookku gate verify <gate id>
```

It exits with 0 if the result can be used and its verdict is `pass`, with 1 for `fail`, and with 2 if the result cannot be used. A later `nookku trace` of a test of the gate changes the seal of the test, so the gate result then cannot be used.

## Limits

- Only a person or CI runs `nookku gate run`. The [relay](../reference/glossary.md#relay) denies it from the model, with each policy.
- Version 1 has no answer key check. A test with `answer_key` fails, so a declared key never passes with no check.
