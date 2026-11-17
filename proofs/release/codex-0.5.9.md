# Codex release proofs of 0.5.9

I ran the Codex proofs of the 0.5.9 release candidate on 2026-11-17, on macOS. The candidate is the same as for [the Claude Code proofs](claude-code-0.5.9.md). The tools were codex-cli 0.169.0 and Docker 29.6.1 (client) and 29.5.2 (server). The proofs of 0.5.8 used codex-cli 0.162.1 ([notes](codex-0.5.8.md)). CI has no Codex pin, so the version is the one that was installed on my machine. I ran the plugin proofs in the worktree of the release branch. I ran the project-hook proofs in the main checkout of the repo, at the commit `75f73209`, as the proof method needs. Each result file records its tested versions. The `claude-code` key of the Codex result files names the Claude Code 2.1.319 on `PATH`. The Codex proofs did not use it as a harness. The script ran each proof again 1 time if it failed. The table gives the run that passed.

## Runs

| Proof | Setup | Result | Data |
|---|---|---|---|
| Hook gate, part A | | 5 of 6 checks pass, 1 fails | [results](../codex-gate/gate.json) |
| Hook gate, part B | | pass, run 2 | [results](../codex-gate/gate.json) |
| P1 to P4 | plugin-codex | pass, run 1 | [results](../plugin-codex/results.json) |
| P1 to P4 | hooks-codex | pass, run 1 | [results](../hooks-codex/results.json) |
| P1 to P4, `--stream` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream/results.json) |
| P1 to P4, `--stream` | hooks-codex | pass, run 1 | [results](../hooks-codex-stream/results.json) |
| P1 to P4, `--stream --on-request` | plugin-codex | pass, run 1 | [results](../plugin-codex-stream-on-request/results.json) |
| P1 to P4, `--stream --on-request` | hooks-codex | pass, run 1 | [results](../hooks-codex-stream-on-request/results.json) |
| P5 to P8, `proof_report.py` | plugin-codex | pass, run 1 | [results](../report/plugin-codex.json) |
| P5 to P8, `proof_report.py` | hooks-codex | pass, run 1 | [results](../report/hooks-codex.json) |
| `proof_telemetry.py` | plugin-codex | pass, run 1 | [results](../telemetry/plugin-codex.json) |
| `proof_telemetry.py` | hooks-codex | pass, run 1 | [results](../telemetry/hooks-codex.json) |
| `proof_performance.py` | plugin-codex | pass, run 1 | [results](../performance/plugin-codex.json) |
| `proof_performance.py` | hooks-codex | pass, run 1 | [results](../performance/hooks-codex.json) |
| `proof_spec_classes.py` | plugin-codex | pass, run 1 | [results](../spec-classes/plugin-codex.json) |
| `proof_spec_classes.py` | hooks-codex | pass, run 2 | [results](../spec-classes/hooks-codex.json) |
| `proof_trace_points.py` | plugin-codex | pass, run 1 | [results](../trace-points/plugin-codex.json) |
| `proof_trace_points.py` | hooks-codex | pass, run 1 | [results](../trace-points/hooks-codex.json) |
| `proof_egress.py` | plugin-codex | pass, run 1 | [results](../egress/plugin-codex.json) |
| `proof_egress.py` | hooks-codex | pass, run 1 | [results](../egress/hooks-codex.json) |
| `proof_egress.py --evaluate` | plugin-codex | pass, run 2 | [results](../egress/plugin-codex-evaluation.json), [test folder](../egress/evaluation/20261117-215920-1af4/) |
| `proof_egress.py --evaluate` | hooks-codex | pass, run 1 | [results](../egress/hooks-codex-evaluation.json), [test folder](../egress/evaluation/20261117-223435-bb63/) |
| P5, `proof_evaluation.py` | plugin-codex | pass, run 1 | [results](../evaluation/plugin-codex.json) |
| P5, `proof_evaluation.py` | hooks-codex | pass, run 1 | [results](../evaluation/hooks-codex.json) |

20 of the 22 model proofs passed at run 1. The hook gate has 1 failed check in part A. The cause is in the next section.

## The failed runs

- **Hook gate, part A: "a script change keeps the trust hash".** Since codex-cli 0.169.0, the trust hash of a plugin hook has 2 parts, `sha256:A/sha256:B`. In 0.162.1, the hash had 1 part. When the proof changes the plugin script, the first part stays the same and the second part changes. For `preToolUse`, the second part changed from `sha256:3643b361…` to `sha256:b55222fd…`. The proof expects the whole hash to stay the same, so this check fails. The other 5 checks of part A pass. The check "the gate finds the changed script" passes, so the gate still finds a changed script and gives its reason. The defect is in the check of the proof, not in the gate. I did not change the proof in this release. [Data](../codex-gate/gate.json).
- **Hook gate, part B, run 1.** Both plugin hooks were `untrusted`, so `nookku start` refused the test and 3 checks of part B failed. The trust steps of the first round did not save. In the gate home, `config.toml` had no `hooks.state` entry. After a second round of the trust steps, `config.toml` had the entries `trusted_hash` and `trusted_content_hash` for both hooks. Run 2 passed 4 of 4 checks. The run of the script after the trust step did not remove the trust: the script removes and adds the plugin again, and the trust entries stayed.
- **The project hooks, trust steps.** The first round of the steps for the project hooks did not save either. In `.proof/codex-hooks/codex-home`, the file `app-server-control/app-server-control.sock` was a link from 2026-10-23 to a socket in `/private/tmp` that no longer existed. The daemon of Codex then failed with `File exists (os error 17)`, and Codex reported "app server did not become ready". The daemon package in that home was also from 0.162.1. The maintainer removed the dangling link and did the steps with `--no-daemon`. The trust entries of the project hooks in `config.toml` are still the old entries with 1 hash. Codex 0.169.0 reported both project hooks as `trusted` with these entries, and the project-hook proofs ran.
- **plugin-codex, `proof_egress.py --evaluate`.** In run 1, the report did not have the denied attempt in its notes (`denied_in_notes: false`). All other checks passed. Its test folder is [`20261117-215654-9ee1`](../egress/evaluation/20261117-215654-9ee1/). Run 2 passed. This is the same failure as run 1 of the plugin in 0.5.8.
- **hooks-codex, `proof_spec_classes.py`, run 1.** Each check of the proof passed (C0, S0 to S4, P5 and P7), but the result was a fail. The list `commands_outside_project` had 1 command: the command that wrote `report.md` with a here-document. The text of the report has an apostrophe. The function `outside` of [proof_report.py](../../scripts/proof_report.py) splits the inner shell text with `shlex.split`. That call raised "No closing quotation", and the function counted the command as outside the project. No command used a path outside the project. This is a defect of the proof check. I did not change the proof in this release. Run 2 passed.
- **hooks-codex, the first set of results (lost by my error).** I ran the 11 hooks-codex proofs one time before the set above. They passed, and the result of `proof_egress.py --evaluate` failed `denied_in_notes` at run 1 and passed at run 2. After the runs, I copied the results to the worktree with a `cp` command that asked before it overwrote, so it copied nothing. Then I ran `git checkout -- proofs` in the main checkout, which removed the tracked result files of that set. I ran all 11 proofs again. The data in this repo is from the second set. The test folder of the failed run of the first set is kept: [`20261117-221505-6138`](../egress/evaluation/20261117-221505-6138/). Its results file is lost. I kept no data of the other runs of the first set. No file outside the proof results changed in the main checkout. After the second set, I copied the results, checked each file with `cmp`, restored the main checkout to `main` and ran `uv sync`.

## The proof in a Koodam Workspace

`scripts/proof_cluster.py plugin-codex` did not run for 0.5.9. It needs a person to log in and to trust the hooks in the Workspace. The last result is from 0.5.7 and it failed at W4 ([results.md](../../docs/results.md#codex-in-a-koodam-workspace), [koodam#243](https://github.com/mohanraj00/koodam/issues/243)).
