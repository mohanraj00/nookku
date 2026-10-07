# Code quality

This spec says what good code is in this repo. Each rule has a reason, one example from this repo, and the check that enforces it. I wrote the rules from the defects that reviews found: the code review of 0.2 ([#43](https://github.com/mohanraj00/verbatim-relay/issues/43) to [#46](https://github.com/mohanraj00/verbatim-relay/issues/46), [#63](https://github.com/mohanraj00/verbatim-relay/issues/63), [#67](https://github.com/mohanraj00/verbatim-relay/issues/67) to [#71](https://github.com/mohanraj00/verbatim-relay/issues/71)), and the reviews of the 0.3 PRs (the issues and PRs that each rule names).

A check is a test, a lint rule, a conformance case or a CI step. "Review" means that no automatic check exists yet. Then the reviewer examines the rule by hand, with the [review guidelines](../CLAUDE.md#review-guidelines). If an open issue adds a check, the rule names that issue.

## Rules

| # | Rule | Check |
|---|---|---|
| 1 | [Fail closed](#1-fail-closed) | Tests in `tests/test_kit.py` and `register.test.ts`, also for the plugin prompt path ([#63](https://github.com/mohanraj00/verbatim-relay/issues/63)) and the deny path ([#68](https://github.com/mohanraj00/verbatim-relay/issues/68)). |
| 2 | [Exact bytes](#2-exact-bytes) | Byte tests of each relay and proxy. Proofs P1 and P2. |
| 3 | [One rule, two languages](#3-one-rule-two-languages) | `test_the_plugin_reads_each_one_line_case_like_the_tap`, the shared `DENY_CASES` table for the deny patterns ([#70](https://github.com/mohanraj00/verbatim-relay/issues/70)), and the shared `DETAIL_CASES` table for the detail of a blocked call ([#88](https://github.com/mohanraj00/verbatim-relay/issues/88)). |
| 4 | [Records](#4-records) | Conformance cases and the CI step for them, also for Unicode ([#43](https://github.com/mohanraj00/verbatim-relay/issues/43), [#65](https://github.com/mohanraj00/verbatim-relay/issues/65)). The shared `RELAY_LINES` table for one reader ([#71](https://github.com/mohanraj00/verbatim-relay/issues/71)). |
| 5 | [No secrets](#5-no-secrets) | Secret tests of the 2 proxies, also for query values ([#69](https://github.com/mohanraj00/verbatim-relay/issues/69)). |
| 6 | [Timeouts](#6-timeouts) | `test_each_timeout_ends_before_the_next_one`, also for the HTTP tap ([#67](https://github.com/mohanraj00/verbatim-relay/issues/67)). |
| 7 | [Errors](#7-errors) | Ruff `E722`. Review. |
| 8 | [Tests](#8-tests) | Review ([#62](https://github.com/mohanraj00/verbatim-relay/issues/62)). |
| 9 | [Dependencies, types and lint](#9-dependencies-types-and-lint) | `test_no_runtime_dependencies`, mypy, ruff, `claude plugin validate`. |
| 10 | [Docs and claims](#10-docs-and-claims) | The stealth gate. Review. |

## 1. Fail closed

**Rule.** If a relay path or a deny path fails, it blocks the message or the tool call. This applies to the plugin and to the hook kit, in each mode.

**Reason.** A relay path that fails open gives the tester's message to the model. The model can then change the message, and the test is not valid.

**Example.** `kit.run_hook` in [src/verbatim_relay/kit.py](../src/verbatim_relay/kit.py) catches each exception in relay mode and blocks the prompt with "Nothing reached the model." In [plugins/claude-code/hooks/register.tsx](../plugins/claude-code/hooks/register.tsx), each gating hook has a `.catch` handler. If the hook fails or runs past its time budget, the handler blocks the prompt or denies the tool call, and it makes no file or state call that can stall again ([#63](https://github.com/mohanraj00/verbatim-relay/issues/63)).

**Check.**

- `tests/test_kit.py`: `test_a_crash_blocks_only_in_relay_mode`, `test_an_unreachable_tap_still_blocks_and_is_recorded`, `test_a_broken_config_blocks_in_relay_mode`.
- `plugins/claude-code/hooks/register.test.ts`: "relay mode with an entry and no test fails closed".
- Review item in CLAUDE.md: "A relay path that fails open."
- [#63](https://github.com/mohanraj00/verbatim-relay/issues/63) added tests for the `.catch` handlers of the plugin hooks. [#68](https://github.com/mohanraj00/verbatim-relay/issues/68) added tests for a PreToolUse deny with a broken config and with relay mode off.

## 2. Exact bytes

**Rule.** The relays and the proxies never change a byte of a message, a reply or a forwarded body. Do not normalize whitespace, line ends or Unicode. A record can hold a decoded or cut copy of a body, but the forwarded bytes stay the same.

**Reason.** The audit compares text byte for byte ([SPEC.md section 3.2](../SPEC.md#32-matching)). A change of one byte is a break.

**Example.** `test_a_gzip_response_is_decoded_in_the_record_only` in [tests/test_backend.py](../tests/test_backend.py): the proxy decodes a copy for the record and forwards the gzip bytes. The case [conformance/cases/altered_input_unicode_nfd](../conformance/cases/altered_input_unicode_nfd) shows that the audit reports a change of Unicode form as a break.

**Check.**

- `tests/test_tap.py::test_the_request_and_response_bytes_pass_unchanged`
- `tests/test_backend.py::test_the_proxy_forwards_each_byte`
- `tests/test_kit.py::test_relay_mode_on_relays_exact_bytes_and_blocks_the_prompt`
- `register.test.ts`: "relay mode sends the exact bytes, shows the exact reply, and keeps the model out".
- Proofs P1 and P2 ([docs/results.md](results.md#1-proofs)), [scripts/proof_backend.py](../scripts/proof_backend.py) and [scripts/proof_model_api.py](../scripts/proof_model_api.py).
- Review item in CLAUDE.md: "A change that lets the relay change a byte".

## 3. One rule, two languages

**Rule.** If Python and the plugin read or match the same input, they use one rule. One shared table of cases tests both. The table comes from `conformance/`.

**Reason.** Two readers with two rules give two results for one agent. The audit then reports a break in one relay only.

**Example.** `contract.parse_reply` accepted a reply with `"error": null`, but `contractShown` in `plugins/claude-code/hooks/core.ts` refused it ([#45](https://github.com/mohanraj00/verbatim-relay/issues/45)). The fix added the table `CONTRACT_LINES` to `register.test.ts`. `kit.deny_pattern` and `denyPattern` now share the table `DENY_CASES` ([#70](https://github.com/mohanraj00/verbatim-relay/issues/70)).

**Check.**

- `tests/test_contract.py::test_the_plugin_reads_each_one_line_case_like_the_tap` checks `CONTRACT_LINES` against `conformance/contract/` and against `contract.parse_reply`.
- `register.test.ts`: "the plugin reads an agent line with the same rule as the Python tap" runs the same table through `contractShown`.
- Deny patterns: `tests/test_kit.py` checks the shared `DENY_CASES` table against `kit.deny_pattern`, and `register.test.ts` ("the deny pattern has the same rule as the hook kit") runs it through `denyPattern` ([#70](https://github.com/mohanraj00/verbatim-relay/issues/70)).
- Relay records: `tests/test_conformance.py` checks the shared `RELAY_LINES` table against `record.read_rows`, and `register.test.ts` runs it through `relayTurns` ([#71](https://github.com/mohanraj00/verbatim-relay/issues/71)).
- The detail of a `blocked_call` row: `tests/test_kit.py` checks the shared `DETAIL_CASES` table against `kit.blocked_detail` and `record.read_rows`, and `register.test.ts` runs it through `blockedDetail` ([#88](https://github.com/mohanraj00/verbatim-relay/issues/88)).

## 4. Records

**Rule.**

- Each writer accepts only Unicode scalar values. A lone surrogate never makes a write raise.
- Each record has one reader with one error rule. An invalid line or a wrong hash stops the read with a clear error.
- A change to the record format needs a SPEC.md change and a conformance case that a person writes by hand.

**Reason.** The records are the evidence. If a writer raises, the record loses an exchange, and the audit names the wrong break. If a reader skips a bad line, a changed record looks exact.

**Example.** `record.read_rows` and `record._validate` in [src/verbatim_relay/record.py](../src/verbatim_relay/record.py) stop at the first invalid line, as the case [conformance/cases/hash_mismatch](../conformance/cases/hash_mismatch) shows. Defects: a lone surrogate made `record.sha256` raise, and the tap wrote no row ([#43](https://github.com/mohanraj00/verbatim-relay/issues/43)). `evaluation._rows` skipped an invalid line with no message ([#71](https://github.com/mohanraj00/verbatim-relay/issues/71)). Now each part reads a record with `record.read_rows`, and the plugin uses `relayTurns` with the same rule.

**Check.**

- `tests/test_conformance.py::test_case` runs each case in `conformance/cases/`.
- The CI step "Conformance cases are up to date" runs `conformance/build.py` and fails on a diff.
- Review item in CLAUDE.md: "A change to the record format or to the audit with no SPEC.md change and no hand-written conformance case."
- Unicode: [#43](https://github.com/mohanraj00/verbatim-relay/issues/43) and [#65](https://github.com/mohanraj00/verbatim-relay/issues/65) added conformance cases and a test for each writer.
- One reader: `tests/test_conformance.py::test_the_plugin_reads_each_relay_line_like_the_python_reader` checks the shared `RELAY_LINES` table ([#71](https://github.com/mohanraj00/verbatim-relay/issues/71)).

## 5. No secrets

**Rule.** No secret header value, query value or key goes into a record. The proxy still forwards it with no change.

**Reason.** The harness model reads the records in the evaluation. A secret in a record goes to the model and to each person who gets the test folder.

**Example.** `backend.secret` and `SECRET_HEADERS` in [src/verbatim_relay/backend.py](../src/verbatim_relay/backend.py) remove the values of secret headers ([SPEC.md section 7.6](../SPEC.md#76-backend-proxies)). Defect: the backend proxy recorded the query as it came, so `?api_key=...` went into `backend.jsonl` ([#69](https://github.com/mohanraj00/verbatim-relay/issues/69)). Now the proxies remove the values of secret query parameters.

**Check.**

- `tests/test_backend.py::test_secret_headers_reach_the_backend_but_not_the_record`
- `tests/test_model_api.py::test_the_api_key_goes_to_the_api_but_not_the_record`
- `tests/test_backend.py::test_secret_query_values_reach_the_backend_but_not_the_record`

## 6. Timeouts

**Rule.** Each wait ends before the wait of the step around it. The order is agent, tap, relay, hook. One test checks the order.

| Wait | Constant | Value |
|---|---|---|
| The stdio tap and the HTTP tap wait for the agent | `stdio.TIMEOUT` | [240 s](../src/verbatim_relay/stdio.py) |
| The test relay waits for the tap | `bridge.TIMEOUT` | [270 s](../src/verbatim_relay/bridge.py) |
| The hook kit relay waits for the tap | `kit.TIMEOUT` | [280 s](../src/verbatim_relay/kit.py) |
| The harness waits for the prompt hook | `kit.HOOK_DEADLINE` | [300 s](../src/verbatim_relay/kit.py) |

**Reason.** If an inner wait is longer than an outer wait, the outer step stops first. Then the hook cannot block the prompt, and the record and the relay disagree.

**Example.** Before 0.3, the HTTP tap waited 300 s for the agent. This was equal to `kit.HOOK_DEADLINE` and more than `kit.TIMEOUT`. Now both taps use `stdio.TIMEOUT`, as one deadline for the full response ([#67](https://github.com/mohanraj00/verbatim-relay/issues/67)).

**Check.**

- `tests/test_timeouts.py::test_each_timeout_ends_before_the_next_one`
- The HTTP tap: `tests/test_timeouts.py` also checks a slow agent, an agent that sends a byte at a time, and a stream with no end ([#67](https://github.com/mohanraj00/verbatim-relay/issues/67)).

## 7. Errors

**Rule.**

- Catch named exceptions. If a catch must be broad (`except Exception`), a comment on the same line gives the reason.
- Do not skip an error with no message.
- An error message names the cause and the next step.

**Reason.** A broad catch hides defects. A silent skip makes a bad record look good. If the tester sees only the cause, the tester does not know what to do.

**Example.** `kit.handle` in [src/verbatim_relay/kit.py](../src/verbatim_relay/kit.py) says "relay mode is on, but no test runs. Start one with: verbatim-relay start. Nothing was sent." Each broad catch in `kit.py`, `bridge.py` and `agent.py` has a comment with its reason. Defects: with a stale `current.json`, the plugin showed only a connection error ([#64](https://github.com/mohanraj00/verbatim-relay/issues/64)). A prompt with a lone surrogate showed "the hook failed (UnicodeEncodeError ...)" ([#65](https://github.com/mohanraj00/verbatim-relay/issues/65)). Both now give the cause and the next step.

**Check.**

- Ruff `E722` refuses a bare `except:`.
- `register.test.ts`: "relay mode with an entry and no test fails closed" and "a current.json whose bridge does not run is no test, and the prompt does not reach the model" check the text "no test runs".
- `tests/test_kit.py::test_a_prompt_with_a_lone_surrogate_is_refused_and_not_recorded` checks the message of [#65](https://github.com/mohanraj00/verbatim-relay/issues/65).

## 8. Tests

**Rule.**

- Each bug fix has a test that fails before the fix. Run the new test on the old code first.
- No test calls a real API or a real model. Use the toy servers in `tests/`.
- No fixed sleep to hide a race. Wait for an event, or give the code a sleep function.

**Reason.** A test that passes before the fix does not prove the fix. A real API makes a test slow and costly, and it gives a different result on each run. A fixed sleep passes on a fast machine and hides the race.

**Example.** [tests/toy_model_server.py](../tests/toy_model_server.py) waits after the first part until the test releases it. `tests/test_otlp.py::test_quiet_waits_for_the_last_request` gives `Receiver.quiet` a sleep function. Defect: `tests/test_contract.py::test_output_before_serve_goes_to_the_log` waits [0.5 s](../tests/test_contract.py) before its request, so it does not show the race of [#62](https://github.com/mohanraj00/verbatim-relay/issues/62). The proofs that use a real harness are local scripts in `scripts/`, not tests (CLAUDE.md "Proofs").

**Check.** Review. [#62](https://github.com/mohanraj00/verbatim-relay/issues/62) removes the fixed sleep from that test.

## 9. Dependencies, types and lint

**Rule.**

- Use the standard library first. Ask the maintainer before you add a runtime dependency. Do not add a GPL or AGPL dependency.
- `mypy` (strict) and `ruff` are clean.
- In `plugins/claude-code/hooks/register.tsx`, a function that takes `$` is a top-level function declaration (CLAUDE.md "Plugin helpers").

**Reason.** The package installs into the tester's project, so it must not add packages there. Types and lint find defects before review. `claude plugin validate` refuses other forms of a helper.

**Example.** [pyproject.toml](../pyproject.toml) has `dependencies = []`. `recordTurns` in [register.tsx](../plugins/claude-code/hooks/register.tsx) is a top-level `async function` that takes `$`.

**Check.**

- `tests/test_package.py::test_no_runtime_dependencies`
- CI job `lint`: `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy` (`strict = true` in `pyproject.toml`).
- CI job `claude-code-plugin`: `claude plugin validate plugins/claude-code`.
- GPL or AGPL dependency: review item in CLAUDE.md.

## 10. Docs and claims

**Rule.**

- Write docs, comments, commit messages and issues in ASD-STE100 (CLAUDE.md "Writing").
- Each number in a doc links to its data and its method. If the measurement does not exist, do not make the claim.
- No banned term in a file, a path or a commit message.

**Reason.** Simple language is easy to review. A number with no data is a claim that nobody can check.

**Example.** The proof table in [docs/results.md](results.md#1-proofs) links each row to its `results.json`. Defects: the README quoted prompt-only runs that the pre-registration excludes ([#9](https://github.com/mohanraj00/verbatim-relay/issues/9)). The README did not say that each benchmark turn was a new harness call ([#8](https://github.com/mohanraj00/verbatim-relay/issues/8)).

**Check.**

- `scripts/stealth.py check` in the CI job `lint`, and `tests/test_stealth.py::test_the_repo_has_no_banned_term`.
- Numbers and language: review. The review item in CLAUDE.md: "A number in a doc with no link to its data and its method."
