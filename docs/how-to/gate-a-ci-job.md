# Gate a CI job on a verdict

This page shows a GitHub Actions job that runs a [scripted test](../reference/glossary.md#scripted-test) and fails when the verdict is `fail`. The test needs no model and no login. The example is [examples/toy-shop-docs/](../../examples/toy-shop-docs/): a toy shop agent that retrieves a section of a local store and cites its locator. [tests/test_example_cited_answers.py](../../tests/test_example_cited_answers.py) runs the same steps in the CI of Nookku.

## What the job checks

- The [app spec](../reference/app-spec.md) declares an [answer key](../reference/app-spec.md#answer-key): for each question of the script, the locator that the reply must cite.
- The `Verdict` table of the app spec sets the most [findings](../reference/glossary.md#findings) of each class. The example permits 0 `agent_error`, 0 `answer_key_mismatch` and 0 `answer_key_missing`.
- `nookku run --script ... --verdict` sends each message of the script to the agent, byte for byte, and computes the verdict ([SPEC.md section 7.14](../../SPEC.md#714-verdict)).

## The workflow file

Put this file in `.github/workflows/agent-verdict.yml` in the repo of your app. Change the [entry](../reference/glossary.md#entry), the app spec and the script to the ones of your app.

```yaml
name: agent-verdict

on:
  pull_request:

permissions:
  contents: read

jobs:
  verdict:
    runs-on: ubuntu-latest
    env:
      # The copy of each seal goes here, so the job must be able to write it.
      NOOKKU_HOME: ${{ runner.temp }}/nookku-home
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Install Nookku
        run: uv tool install nookku
      - name: Write the config
        run: nookku init plugin --entry "python3 agent.py" --spec APP_SPEC.md
      - name: Register the egress answer
        # The example agent calls no service. Give the services of your agent here.
        run: |
          echo '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}' \
            | nookku register
      - name: Run the scripted test
        run: nookku run --script script.jsonl --verdict --no-evaluate
      - name: Keep the test folder
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nookku-tests
          path: .nookku/tests/
          include-hidden-files: true
```

- `nookku init plugin` writes `.nookku/config.json`. The job does not use a [harness](../reference/glossary.md#harness), so the [relay](../reference/glossary.md#relay) form has no effect here.
- `nookku register` gives the egress answer. A test start needs an answer from the last 30 minutes ([SPEC.md section 7.11](../../SPEC.md#711-egress-discovery)).
- `--no-evaluate` stops the [evaluation](../reference/glossary.md#evaluation) prompt, because no model runs in the job.
- The last step keeps the [test folder](../reference/glossary.md#test-folder), so you can read `verdict.json` and `findings.json` after a failure. The folder is in `.nookku/`, and `upload-artifact` does not upload a hidden folder by default. Thus the step sets `include-hidden-files: true`.

## The exit codes

`nookku run --script ... --verdict` exits with one of 2 codes ([SPEC.md section 7.10](../../SPEC.md#710-scripted-tests)):

| Code | Meaning | The job |
|---|---|---|
| 0 | The test ran, the [audit](../reference/glossary.md#audit) is clean, and the verdict is `pass`. | passes |
| 1 | The test did not start, a turn has no reply, the audit is not clean, the Codex hooks changed, or the verdict is not `pass`. | fails |

The output names the reason. For a `fail` verdict, a line gives each class that is above its limit, for example `Verdict: fail. answer_key_mismatch: 1, the limit is 0.`

## Run the example on your computer

From the folder of a copy of `examples/toy-shop-docs/`, run the 3 commands of the job:

```bash
nookku init plugin --entry "python3 agent.py" --spec APP_SPEC.md
```

```bash
echo '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}' | nookku register
```

```bash
nookku run --script script.jsonl --verdict --no-evaluate
```

The last command prints `Verdict: pass (3 limits).` and `PASS`, and exits with 0.

## Limits

- The answer key checks the value of a field of the reply. It does not check that the agent read the cited section. The [trace](../reference/glossary.md#trace) check `citation_not_read` checks that, but it needs the tool results of a model session ([SPEC.md section 8.6](../../SPEC.md#86-findings)).
- A set of tests with one verdict is a gate run. [Gate a release](gate-a-release.md) gives the steps.
