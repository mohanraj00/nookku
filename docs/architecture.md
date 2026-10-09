# Architecture

This page shows the parts of Nooku and how the data goes between them. [SPEC.md](../SPEC.md) defines each part exactly. This page tells you why each part exists and where to read more.

## The problem

A tester talks to a chat agent through a coding [harness](reference/glossary.md#harness): Claude Code or Codex. If the harness model carries the messages, it also writes them. Then it judges its own text. Nooku takes the model out of the conversation, and keeps 2 records that a third program can compare.

## Data flow

This diagram shows a test with an entry. With no entry, the relay sends each message to a tap in HTTP mode, and no bridge runs ([how-to/http-tap.md](how-to/http-tap.md)).

```mermaid
flowchart TB
    tester([Tester]) -->|types a message| harness[Harness: Claude Code or Codex]
    harness -->|prompt hook| relay[Relay: plugin or hook kit]
    currentrec[(current.json)] -->|tap URL| relay
    relay -->|HTTP POST with a contract JSON body| tap[Tap]
    tap -->|the same bytes on stdin| entry[Entry]
    entry --> app[Your app]
    app -->|reply| entry
    entry -->|a contract JSON line on stdout| tap
    tap -->|the same bytes in the HTTP response| relay
    relay -->|plugin: a chat row| tester
    relay -.->|writes| relayrec[(relay.jsonl)]
    relayrec -->|hook kit| viewer[Viewer: nooku view]
    viewer -->|shows the reply| tester
    tap -.->|writes| taprec[(tap.jsonl)]

    bridge[Bridge] ==>|starts| otlp[OTLP receiver]
    bridge ==>|starts| bproxy[Backend proxy]
    bridge ==>|starts| mproxy[Model API proxy]
    bridge ==>|starts| tap
    bridge ==>|starts| entry
    bridge -.->|writes| currentrec
    bridge -.->|writes model_session rows| taprec

    app -->|HTTP| bproxy --> backend[Backend service]
    app -->|HTTP| mproxy --> api[Model API]
    app -->|OTLP| otlp
    bproxy -.->|writes| backendrec[(backend.jsonl)]
    mproxy -.->|writes| modelrec[(model_api.jsonl)]
    otlp -.->|writes| otelrec[(otel.jsonl)]
    app -.->|the harness binary writes| hsessions[(Harness session files)]
    hsessions -->|the bridge copies| sessions[(sessions/)]

    bridge ==>|runs at the end| trace[[Trace]]
    bridge ==>|runs at the end| audit{{Audit}}
    bridge ==>|runs at the end| seal[Seal]
    taprec --> trace
    sessions --> trace
    backendrec --> trace
    modelrec --> trace
    otelrec --> trace
    trace -.->|writes| tracerec[(trace.jsonl)]
    trace -.->|writes| findingsrec[(findings.json)]
    relayrec --> audit
    taprec --> audit
    audit -.->|writes| auditrec[(audit.json)]
    seal -.->|writes| sealrec[(seal.json)]
    tracerec --> eval[Evaluation by the harness model]
    findingsrec --> eval
    auditrec --> eval
    eval -.->|writes| report[(report.md)]
```

The solid lines carry the conversation and the data that a part reads. The dotted lines write a file. The thick lines show the parts that the bridge starts, and the steps that it runs at the end. The [relay](reference/glossary.md#relay), the [tap](reference/glossary.md#tap) and the proxies run on the tester's machine, on `127.0.0.1`.

The relay sends each message as an HTTP POST with a contract JSON body ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). The tap writes the same bytes as one line to the stdin of the entry. It sends the reply line back to the relay with no change.

## The relays

A relay is the harness extension that carries each message and each reply. There are 2 relays ([SPEC.md section 5](../SPEC.md#5-relays)):

- **The Claude Code plugin.** It uses function hooks, which are early access. It shows each reply as a row in the chat that the model does not receive. Read [how-to/claude-code-plugin.md](how-to/claude-code-plugin.md).
- **The hook kit.** It uses the classic hooks that Codex and Claude Code share. It cannot show text in the chat, so `nooku view` shows each reply in a second terminal. Read [how-to/claude-code-hook-kit.md](how-to/claude-code-hook-kit.md) or [how-to/codex.md](how-to/codex.md).

In [relay mode](reference/glossary.md#relay-mode), the relay takes each prompt before the model sees it. It sends the prompt to the tap and blocks it from the model. The relay also denies a model tool call that names the address of the tap or the agent. It also denies a call that changes the files of a test. The deny is best effort. [limits.md](limits.md) tells you what it does not stop.

A relay fails closed. If it cannot send a message, the message still does not go to the model. The relay shows the error and records it as a relay error ([SPEC.md section 5](../SPEC.md#5-relays)).

## The tap

The tap is a proxy between the relay and the agent. It forwards each request and each response with no change, and it writes the tap record. It has 2 modes ([SPEC.md section 4](../SPEC.md#4-tap)):

- **Stdio mode.** The tap starts the [entry](reference/glossary.md#entry) and speaks the [agent contract](reference/glossary.md#agent-contract) with it. A test uses this mode.
- **HTTP mode.** The tap is in front of an agent that is already an HTTP server. Read [how-to/http-tap.md](how-to/http-tap.md).

## The entry and the agent contract

The entry is a thin wrapper that starts your app and speaks the agent contract on stdin and stdout. The contract is one JSON line in for each message, and one JSON line out for each reply ([SPEC.md section 6](../SPEC.md#6-agent-contract-version-1)). The entry is test code, not app code. It is in `.nooku/`, and your app's code does not change.

This is the plumbing that a test needs. You write the entry once. You change it when the start or the wiring of your app changes. In Python, `nooku.agent.serve()` speaks the contract for one function. Read [how-to/connect-your-agent.md](how-to/connect-your-agent.md).

## One turn

This diagram shows one message in a test with an entry. The plugin and the hook kit do the same steps.

```mermaid
sequenceDiagram
    actor Tester
    participant Harness
    participant Relay as Relay (plugin or hook kit)
    participant Tap
    participant Entry as Entry and app
    participant Model as Harness model

    Tester->>Harness: types a message
    Harness->>Relay: prompt hook
    Relay->>Relay: read the tap URL in current.json and the history in relay.jsonl
    Relay->>Tap: HTTP POST with a contract JSON body
    alt the tap answers
        Tap->>Entry: the same bytes as one line on stdin
        Entry-->>Tap: one contract JSON line on stdout, or no line in 240 s
        Tap->>Tap: write an exchange row to tap.jsonl, or an unparsed row if the reply line breaks the contract
        Tap-->>Relay: 200 with the same bytes, or an error status (502 for an unparsed reply)
        Relay->>Relay: write a turn to relay.jsonl, with ok: true only for a 200
        Relay-->>Tester: show the reply or the error
    else the tap does not answer
        Relay->>Relay: write a turn with ok: false to relay.jsonl
        Relay-->>Tester: show the relay error
    end
    Relay-->>Harness: block the prompt
    Note over Model: The model gets nothing.
```

- If the agent sends an error, the tap sends status 500. If the agent sends no reply line in [240 seconds](#timeouts), the tap stops the agent and sends status 504 ([SPEC.md section 4.2](../SPEC.md#42-stdio-mode)).
- If the tap does not answer, for example because the bridge stopped, the relay writes the turn with `ok: false`. It still blocks the prompt, and the model gets nothing ([SPEC.md section 5](../SPEC.md#5-relays)).
- The plugin shows the reply as a chat row, and then writes the turn. The hook kit writes the turn, and the viewer shows it from `relay.jsonl`.
- The relay sends only the turns with `ok: true` as the history.

## The bridge

The [bridge](reference/glossary.md#bridge) is a background process that runs one test ([SPEC.md section 7.2](../SPEC.md#72-start-and-end)). `nooku start` starts it. The bridge then:

1. starts the OTLP receiver, the backend proxies and the model API proxies;
2. starts the entry through the tap in stdio mode;
3. watches for the Claude Code sessions that a process of the entry runs, and writes a `model_session` row to `tap.jsonl` for each one ([SPEC.md section 7.3](../SPEC.md#73-model-sessions)).

`nooku end` stops it. The bridge then:

1. stops the entry and the proxies;
2. finds the Codex sessions of the app, and writes a `model_session` row to `tap.jsonl` for each one;
3. copies each session file into the [test folder](reference/glossary.md#test-folder);
4. builds the [trace](reference/glossary.md#trace), writes `audit.json` and writes the [seal](reference/glossary.md#seal).

If the trace, the audit or the seal fails, the bridge writes the error to `bridge.log` and does the next step. The test still ends ([SPEC.md section 7.2](../SPEC.md#72-start-and-end)).

## The test lifecycle

This diagram shows the states of a test, and the steps that change the state.

```mermaid
stateDiagram-v2
    state "Off: no test runs" as Off
    state "Running: the bridge runs, and current.json names it" as Running
    state "Ended: the bridge ran its end steps" as Ended
    state "Evaluating: the harness model writes report.md" as Evaluating

    [*] --> Off
    Off --> Running: nooku start
    Running --> Ended: the prompt nooku end
    Running --> Ended: nooku end in a shell, or /nooku end
    Running --> Off: the bridge stopped before its end steps, and a check removed the stale current.json
    Ended --> Evaluating: the prompt nooku end, if evaluate is not false
    Ended --> Running: nooku start
    Evaluating --> Off: the model wrote report.md
    Evaluating --> Ended: the model wrote no report.md
    note right of Ended: With "evaluate" false, the test stays here and gets no evaluation.
```

- There are 2 ways to end a test ([SPEC.md section 9.1](../SPEC.md#91-start)). The prompt `nooku end` ends the test and starts the evaluation in one step. `nooku end` in a shell, or `/nooku end` in the plugin, ends the test with no evaluation.
- A later prompt `nooku end` starts the evaluation of the latest test, if that test ended and has no `report.md`. A new test with `nooku start` becomes the latest test, so the test before it gets no evaluation.
- If the configuration has `"evaluate": false`, no test gets an evaluation ([reference/config.md](reference/config.md#test-keys)).
- If the bridge stops before its end steps, `current.json` stays. `start`, `end` and `status` check if the bridge of `current.json` runs. If it does not run, they remove the stale file ([SPEC.md section 7.2](../SPEC.md#72-start-and-end)). The hook kit does this check before each prompt. The plugin does it after a POST to the tap fails. A test with a stale `current.json` has no end time, so it gets no evaluation.

## The proxies and the receiver

These parts record what the app does to answer a message. Each one is independent of the app's code, except the OTLP receiver.

- **Backend proxies.** One recording proxy for each HTTP service of the app. The bridge gives the app the proxy URL in the service's environment variable ([SPEC.md section 7.6](../SPEC.md#76-backend-proxies)). Read [how-to/add-a-backend.md](how-to/add-a-backend.md).
- **Model API proxies.** One recording proxy for the Anthropic API and one for the OpenAI API, in `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL` ([SPEC.md section 7.7](../SPEC.md#77-model-api-proxies)).
- **OTLP receiver.** It takes the OpenTelemetry spans and logs of the app ([SPEC.md section 7.5](../SPEC.md#75-otlp-receiver)).

Read [how-to/record-model-calls.md](how-to/record-model-calls.md) for the last two. The proxies remove the values of secret headers and secret query parameters from the record, but forward them with no change.

## The model sessions

If your app runs its own Claude Agent SDK or Codex sessions, the harness binary writes a session file for each one. The test copies these files. They hold each tool call of the app's model, with its arguments and its result. The harness writes them, not your app, so their format can change between harness versions ([SPEC.md section 7.3](../SPEC.md#73-model-sessions)).

## The audit

The [audit](reference/glossary.md#audit) compares the relay record with the tap record ([SPEC.md section 3](../SPEC.md#3-audit)). It aligns the tester messages with the agent inputs, and then it compares each reply. It compares bytes. It does not normalize whitespace, line ends or Unicode. It reports 7 break classes: `altered_input`, `injected_input`, `duplicate_send`, `out_of_order`, `not_delivered`, `altered_reply` and `unshown_reply`.

The audit fails closed. If a record is missing or invalid, it exits with 2 and reports no result. It never reports clean on a record that it cannot read.

## The seal

At the end of a test, the bridge writes the SHA-256 of each file of the test folder to `seal.json`. It also writes a copy outside the project ([SPEC.md section 7.4](../SPEC.md#74-seal)). `nooku verify` shows each file that changed after the end. The seal does not stop a change. It makes a change visible.

## The trace and the findings

The trace, `trace.jsonl`, joins the session files, `otel.jsonl`, `backend.jsonl` and `model_api.jsonl` into one record. Each item has its turn and a pointer to its line in the source file ([SPEC.md section 8](../SPEC.md#8-trace)). 12 checks write `findings.json`, for example a tool call that failed or a turn in which no model ran ([SPEC.md section 8.6](../SPEC.md#86-findings)). The [findings](reference/glossary.md#findings) do not change the exit code of the audit.

```mermaid
flowchart TB
    manifestrec[(manifest.json)] -->|model_sessions| sreaders[Session readers: Claude Code and Codex]
    sessions[(sessions/)] --> sreaders
    otelrec[(otel.jsonl)] --> oreader[OTLP reader]
    backendrec[(backend.jsonl)] --> breader[Backend reader]
    modelrec[(model_api.jsonl)] --> mreader[Model API reader]
    sreaders -->|messages, tool calls, commands| items[Items in time order]
    oreader -->|spans and logs| items
    breader -->|HTTP calls| items
    mreader -->|messages| items
    taprec[(tap.jsonl)] -->|exchange rows| windows[Turn windows: from started to ts of each exchange]
    items --> assign[Give each item the turn whose window holds its time]
    windows --> assign
    assign -.->|writes| tracerec[(trace.jsonl)]
    assign --> checks[12 checks]
    sreaders -->|sessions and MCP servers| checks
    taprec -->|status of each exchange| checks
    checks -.->|writes| findingsrec[(findings.json)]
    taprec --> transcript[nooku transcript --trace]
    tracerec --> transcript
    findingsrec --> transcript
    sealrec[(seal.json)] -->|seal check| transcript
    transcript --> eval[Evaluation by the harness model]
    findingsrec --> eval
    auditrec[(audit.json)] --> eval
    eval -.->|writes| report[(report.md)]
```

- The bridge builds the trace at the end of a test, from the copied session files in `sessions/` and the list of model sessions in `manifest.json`.
- The window of a turn is from `started` to `ts` of its exchange row in `tap.jsonl`. An item in no window has no turn ([SPEC.md section 8.3](../SPEC.md#83-turns)).
- `nooku transcript --trace` shows each turn from `tap.jsonl`, with its items and its findings, and the result of the seal ([SPEC.md section 9.2](../SPEC.md#92-evaluation-prompt)).

## The evaluation

At the prompt `nooku end`, the relay ends the test and gives the harness model the [evaluation](reference/glossary.md#evaluation) prompt ([SPEC.md section 9](../SPEC.md#9-evaluation)). The model did not see the conversation while you talked. It reads the transcript with the trace, the findings and the audit. It reads your app's code and rules, and it checks the app's state with read-only commands. Then it writes `report.md`. After a test, the relay denies model writes to the test folder, except `report.md`.

A report is a model answer, so it can be wrong. [evaluation-example.md](evaluation-example.md) shows one report and what the model got wrong.

## Timeouts

Each wait on the relay path ends before the wait around it, so that the relay can still block the prompt ([SPEC.md section 4.3](../SPEC.md#43-timeouts)). The order is the agent, the tap, the relay and the hook. The test [tests/test_timeouts.py](../tests/test_timeouts.py) checks the order.

| Order | Wait | Seconds | Constant |
|---|---|---|---|
| 1 | The tap waits for the agent, in HTTP mode and in stdio mode. | [240](../src/nooku/stdio.py#L24) | `stdio.TIMEOUT` |
| 2 | The tap answers the relay, at most [5 seconds](../tests/test_timeouts.py#L22) after the agent timeout. | [245](../tests/test_timeouts.py#L22) | `stdio.TIMEOUT + ANSWER` |
| 3 | The hook kit waits for the tap of a test. | [270](../src/nooku/bridge.py#L38) | `bridge.TIMEOUT` |
| 3 | The hook kit waits for a tap in HTTP mode, with no test. | [280](../src/nooku/kit.py#L34) | `kit.TIMEOUT` |
| 4 | The harness stops the `UserPromptSubmit` hook of the hook kit. | [300](../src/nooku/kit.py#L37) | `kit.HOOK_DEADLINE` |

Each number links to its constant. The [5 seconds](../tests/test_timeouts.py#L22) of order 2 is the `ANSWER` limit of the test. The plugin sets no timeout of its own. It waits for the answer of the tap. [tests/test_docs.py](../tests/test_docs.py) checks that this table matches the constants.

## Where to read the code

| Part | Code |
|---|---|
| Hook kit | [src/nooku/kit.py](../src/nooku/kit.py) |
| Plugin | [plugins/claude-code/hooks/register.tsx](../plugins/claude-code/hooks/register.tsx), [core.ts](../plugins/claude-code/hooks/core.ts) |
| Tap, HTTP mode | [src/nooku/tap.py](../src/nooku/tap.py), [adapters.py](../src/nooku/adapters.py) |
| Tap, stdio mode | [src/nooku/stdio.py](../src/nooku/stdio.py) |
| Agent contract | [src/nooku/contract.py](../src/nooku/contract.py), [agent.py](../src/nooku/agent.py) |
| Bridge | [src/nooku/bridge.py](../src/nooku/bridge.py) |
| Proxies and receiver | [backend.py](../src/nooku/backend.py), [model_api.py](../src/nooku/model_api.py), [otlp.py](../src/nooku/otlp.py) |
| Records and audit | [record.py](../src/nooku/record.py), [audit.py](../src/nooku/audit.py) |
| Seal | [seal.py](../src/nooku/seal.py) |
| Trace and evaluation | [trace.py](../src/nooku/trace.py), [evaluation.py](../src/nooku/evaluation.py), [evaluate.md](../src/nooku/evaluate.md) |
| Read check of the deny | [commands.py](../src/nooku/commands.py) |
