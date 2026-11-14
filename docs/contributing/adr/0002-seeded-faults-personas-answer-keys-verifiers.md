# ADR 0002: Seeded faults, persona sets, answer keys and verifiers

Status: accepted on 2026-11-14. Date: 2026-11-13. Issues: [#546](https://github.com/mohanraj00/nookku/issues/546), [#547](https://github.com/mohanraj00/nookku/issues/547), [#548](https://github.com/mohanraj00/nookku/issues/548) and [#549](https://github.com/mohanraj00/nookku/issues/549).

## Context

The 2026-11 planning review asks for one design record before the code of #546 to #549. The record must answer 4 questions:

1. The command names. `nookku verify` already checks the [seal](../../reference/glossary.md#seal), so #546 needs a different name.
2. How #547 relates to #520. A declared persona set is deterministic. A simulated user is not, unless the run records and replays it.
3. The match rule of #548 and its effect on the verdict.
4. What a verifier is for #549, because Nookku has no verifier object today.

The gate run of #574 ([SPEC.md section 7.15](../../../SPEC.md#715-gate-run)) is the container for these items. The constitution gives 2 rules that this record keeps ([Verdicts](../../../CONSTITUTION.md#verdicts)):

- A deterministic check can fail a verdict.
- A model judgment fails a verdict only when the app spec opts in. The default verdict is reproducible.

Some parts exist now, in PRs that the owner did not merge yet:

- [#592](https://github.com/mohanraj00/nookku/pull/592) adds the answer key check to the app spec and the [trace](../../reference/glossary.md#trace), with the [finding](../../reference/glossary.md#findings) classes `answer_key_mismatch` and `answer_key_missing`.
- [#593](https://github.com/mohanraj00/nookku/pull/593) adds the replay check to the gate run, with the checks `missing_base` and `changed_turns`.

## Decision 1: the command names

- #546 uses `nookku faults`. The command runs each check of the trace on its seeded faults. It does not use the name `verify`, `check` or `prove`. `verify` checks a seal, `check` runs a short test of the [entry](../../reference/glossary.md#entry), and the proofs are the scripts in `scripts/`.
- #549 uses `nookku verifier run <claims> --entry <name>`.
- #548 uses `nookku adjudicate <test> --turn <n> --outcome <outcome> --reason <text>`.

### `nookku faults`

- A seeded fault is a conformance case of the trace that expects one or more findings of a class. The cases are in `conformance/trace/` now. Each case gets a file `faults.json` that names each expected finding: the class and the turn.
- `nookku faults` runs the trace on the records of each case, with no model. A check that does not give each expected finding is a missed fault. The command exits with 1 if a fault is missed, or if a class of section 8.6 has no seeded fault.
- The report lists each fault, its case and its result. With `--json`, it is JSON.
- The release proofs run `nookku faults` and commit the report with the version that it records.
- A [scripted test](../../reference/glossary.md#scripted-test) with a seeded fault, as in #592 and #593, stays a pytest test. It also proves the start, the seal and the verdict, which a trace case does not.

## Decision 2: persona sets (#547) and the simulated user (#520)

- A persona set is a gate file. Each test of the gate file names one persona with the key `persona` and one script. The gate result gives the verdict of each test, so the result shows each persona.
- A persona of #547 is a record only, as SPEC.md section 7.15 says now. The test sends the messages of its script. Thus a persona set is deterministic.
- A simulated user of #520 writes each next message. Its messages are not deterministic. Thus a test with a simulated user is a source of scripts, not a test of a gate run:
  1. The [tester](../../reference/glossary.md#tester) runs the simulated user one time. The [relay record](../../reference/glossary.md#relay-record) marks each message that the simulated user wrote.
  2. `nookku script save` writes a script from the test, byte for byte.
  3. The gate run sends the script again and compares the replies with the replay check of #593.
- A gate run does not start a simulated user. Thus the gate verdict stays reproducible.
- The decision of 2026-10-24 on #520 stays: the [harness model](../../reference/glossary.md#harness-model) plays the simulated user in a new session, with only the persona and the goal.
- A comparison with an earlier run (#547) is the replay check of #593, one test for each persona.

## Decision 3: the match rule (#548) and the verdict

- The match rule is the rule of #592 (SPEC.md section 7.17 in that PR). The app spec declares the key file, a field path, the match `exact` or `number`, and a tolerance for `number`. The check is deterministic and uses no model.
- #548 asks that each key row declares its rule. #592 has one rule for each key. Thus #548 adds an optional `match` and `tolerance` to each answer of the key file. An answer with no rule uses the rule of the app spec.
- An adjudication is a row in `adjudications.jsonl` in the [test folder](../../reference/glossary.md#test-folder). The row has the question, the turn, the outcome, the reason and the author. The outcomes are a closed set: `agent_wrong`, `key_wrong` and `both_acceptable`.
- Only a person writes an adjudication, with `nookku adjudicate`. The guard denies a model write of the file, and the [relay](../../reference/glossary.md#relay) denies a model command that runs `nookku adjudicate`, as for `nookku script` (SPEC.md section 7.10). Thus the author is always a person, and the row records the name that the person gives.
- `nookku adjudicate` writes the seal again, as `nookku trace` does. Thus a gate result that pinned the test cannot be used after an adjudication, and the gate must run again.
- A mismatch with the outcome `key_wrong` or `both_acceptable` does not count against the limit of `answer_key_mismatch`. An open mismatch and an `agent_wrong` mismatch count.
- `findings.json` keeps each mismatch. The verdict gives the count before and after the adjudications.
- The gate key `answer_key` of SPEC.md section 7.15 fails now in each case. #548 removes it and uses the `Answer key` section of the app spec and the limit of `answer_key_mismatch`.

## Decision 4: what a verifier is (#549)

- A verifier is an entry: a program that `entries` names. Nookku sends it each claim as one JSON line on stdin. The verifier writes one JSON line on stdout: `{"verdict": "supported"}` or `{"verdict": "refuted"}`.
- A model verifier is an entry that calls a model. Nookku does not call a model.
- A claim set is a declared JSON file: `source`, `version`, and a list of claims. Each claim has `id`, `text` and `seeded`. `seeded: true` marks a seeded false claim.
- `nookku verifier run` writes `verifier.json`: the verdict of each claim, the count of seeded false claims that the verifier refuted, the count of true claims that it refuted, and both rates with their counts.
- A rate is a measurement, not a verdict. A gate limit on a rate is possible only when the app spec opts in, because a model verifier is not deterministic.
- The docs give the method and the limits: the rate is true only for the claim set and the version of the verifier.

## Options that I did not take

- **One command `nookku eval` for all 4 items.** One command with 4 modes is hard to read, and each mode has other files.
- **A simulated user in a gate run.** The gate verdict is then not reproducible, and the constitution makes reproducible the default.
- **An adjudication in the gate file.** The gate file declares tests before they run, so it cannot hold an adjudication of a mismatch that a later test finds.
- **A verifier inside Nookku.** Nookku then calls a model, and it has no model call today.

## What the owner decided

The owner accepted this record on 2026-11-14, with the command name `nookku faults`. Thus each decision of this record applies:

- The 4 command names.
- That a gate run does not start a simulated user.
- That only a person writes an adjudication.
- That a verifier is an entry.
