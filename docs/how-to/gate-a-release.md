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

## Check the answers with an answer key

A test of a gate file has no key `answer_key`. The app spec declares the answer key, and each test with that spec checks it ([app-spec.md](../reference/app-spec.md#answer-key), [SPEC.md section 7.17](../../SPEC.md#717-answer-key)). Add the section `Answer key` to the app spec, for example the toy shop key of stock counts:

```markdown
## Answer key

| File | Field | Match | Tolerance |
|---|---|---|---|
| `keys/stock.json` | `count` | number | 0.5 |
```

Then give the test a limit of `answer_key_mismatch`. With the limit 0, one reply that does not match its answer fails the test:

```json
{"name": "stock", "script": "scripts/stock.jsonl", "limits": {"answer_key_mismatch": 0}}
```

- The check compares each answer with no model, so the result is the same on each run.
- A key that the check cannot use fails the test with each limit.
- To stop the [harness model](../reference/glossary.md#harness-model) from a read of the key, run `nookku policy set answer_keys keys/stock.json`.
- Nookku 0.6.1 and older accepted the key `answer_key` in a test, and the test always failed. Now `nookku gate run` refuses such a gate file, runs no test and exits with 2. The error names the `Answer key` section. Remove the key from the test and declare the key in the app spec.

## Compare a test with a base test

A replay check compares the replies of a new test with the replies of an older test, turn by turn, byte for byte. It uses no model. Give the test id of the older test and the most changed turns:

```json
{"name": "refund", "script": "scripts/refund.jsonl", "replay": {"base": "20261101-101500-3f2a", "changed": 0}}
```

- `base` is a [test folder](../reference/glossary.md#test-folder) in the tests folder. The gate run does not run it again. Before the first test starts, the run pins the SHA-256 of its [relay](../reference/glossary.md#relay) and [tap records](../reference/glossary.md#tap-record).
- The check `missing_base` fails if the base test does not exist or its [seal](../reference/glossary.md#seal) is not intact.
- The check `changed_turns` fails if more turns changed than `changed`. The text names each changed turn, and `result.json` records the base test id, the new test id and the count.
- To see the words that changed, run `nookku replay` with the same script and `--base`.

## Test a set of personas

A persona set is a gate file with one test for each persona ([ADR 0002](../contributing/adr/0002-seeded-faults-personas-answer-keys-verifiers.md#decision-2-persona-sets-547-and-the-simulated-user-520)). The `name` of the test names the persona, and `persona` gives a persona file with the form of `nookku run --persona` ([cli.md](../reference/cli.md#nookku-run)):

```json
{"v": 1, "tests": [
 {"name": "new_customer", "script": "scripts/new_customer.jsonl", "persona": "personas/new_customer.json"},
 {"name": "return_customer", "script": "scripts/return_customer.jsonl", "persona": "personas/return_customer.json", "replay": {"base": "20261101-101500-3f2a", "changed": 0}},
 {"name": "short_sentences", "script": "scripts/short_sentences.jsonl", "persona": "personas/short_sentences.json"}
]}
```

1. Run each persona one time with a simulated user: `nookku run --persona personas/return_customer.json`.
2. Save the test as a script: `nookku script save <test id>`. The command writes `.nookku/scripts/<test id>.jsonl`. Copy the file to `gates/scripts/return_customer.jsonl`.
3. Add the test of the persona to the gate file. The gate run sends the messages of the script, so the result is the same on each run. The gate run never starts a simulated user.

`result.json` gives the verdict and the checks of each test, and `persona` gives the persona, the goal and the SHA-256 of the copy. The output line of each test names its persona. If a persona file is not valid, its test does not run, and the check `missing_test` fails. To compare each persona with an earlier run, give each test a replay check.

## Check a proof file

A gate run can also check a file that a test or an analysis made, for example a measure report. Add the list `proofs` next to `tests`:

```json
"proofs": [{"path": "reports/measure.json", "max_age": 86400, "bound": {"field": ["error_bound"], "most": 0.05}}]
```

- `path` is relative to the folder of the gate file. The run reads the file after the last test, and the seal covers its copy.
- `max_age` is the most age of the file in seconds. An older file fails with the reason `stale`.
- `bound` is optional. `field` gives the keys of a number in the JSON file. A value above `most` fails with the reason `above_limit`.
- A file that the run cannot read fails with the reason `missing`.

## Run the set

1. Register the egress answer of the app, as for each test (`nookku register`). The gate run uses one answer for all of its tests.
2. Run the gate with the digest of the thing that you test:

   ```bash
   nookku gate run gates/gate.json --subject "sha256:ab12cd34"
   ```

The command prints the lines of each test, one line for each test and the aggregate verdict. It exits with 0 if the aggregate verdict is `pass`, with 1 if it is `fail`, with 3 if it is `inconclusive`, and with 2 if no test ran.

A test is inconclusive if a call failed for a cause outside the app, and no good call followed it: the model provider gave the HTTP status 429, or a service of the test refused the connection ([SPEC.md section 8.13](../../SPEC.md#813-outside-failures)). An inconclusive result is not a pass and not a fail. Stop the release job, and run the gate again when the limit is gone or the service runs.

The result folder is `.nookku/gates/<gate id>/`. In CI, set `NOOKKU_HOME` to a folder that the job can write, because the copy of the seal goes there.

## Read the result in a CI job or a rollout controller

`result.json` is plain JSON, so a reader needs no Nookku process. [Gate a rollout on a gate result](gate-a-rollout.md) names each file and each field that a controller reads, with an example. Do these steps:

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

Step 3 shows only that `result.json` did not change. It does not check the test folders. For a full check, run `nookku gate verify` on a machine that has the gate folder, the tests folder and the copies of the seals:

```bash
nookku gate verify <gate id>
```

It exits with 0 if the result can be used and its verdict is `pass`, with 1 for `fail`, with 3 for `inconclusive`, and with 2 if the result cannot be used. For an inconclusive result, the output gives the count of the inconclusive tests. A later `nookku trace` of a test of the gate changes the seal of the test, so the gate result then cannot be used.

## Limits

- Only a person or CI runs `nookku gate run`. The relay denies it from the model, with each policy.
- `nookku gate verify` cannot use a gate folder of Nookku 0.6.1 or older whose `gate.json` has the key `answer_key`. It exits with 2. Run the gate again with this version.
