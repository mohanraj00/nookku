# Evaluate test {test}

The tester ended test {test} of the app in this project. Evaluate the app. Use only the records of the test, the project files and read-only commands. You did not see the conversation while the tester talked, so judge the record, not your memory.

The test folder is `{folder}`.

## Read

1. Run `nookku transcript --trace --test {test}`. If its first line starts with `Record: INVALID`, go to "Invalid record" below. Else, its first line says if a record changed after the end of the test. If the seal is broken, say so in the notes, and do not trust the changed files. Then the transcript shows each turn as the app received it and sent it. Under each turn, it shows the model items of the app: the messages, the tool calls with their input and result, and the commands.
2. Read `findings.json` and `audit.json` in the test folder. A finding is a fact, not yet an issue. The audit shows if the words of a turn changed between the tester and the app.
   To read a file of the test folder in a shell, use `cat`, `sed -n`, `jq` or `grep`. The relay denies other commands that name `.nookku`.
   Read `egress` in `manifest.json`: the egress parts of the agent, `unseen` (the parts that no proxy saw), `driver` (the databases that the driver trace records) and `proxies`. Each `unseen_call` finding is a call of the app that no proxy saw.
   Each database query of the transcript names its source. `proxy` is the Postgres proxy: it is outside the app process, and it records the rows of each answer. `driver trace from the app process` is a span of the database driver of the app. A driver trace has no rows, and it can hide parameter values. Thus do not judge the rows of a query from a driver trace. Check the state of the database with a read-only query.
3. If the test folder has the file `notes.jsonl`, read it. Each line is a note of the tester on one turn: `turn`, `rating` (`up`, `down` or `null`) and `comment` (text or `null`). `turn` is the number of the turn in `relay.jsonl`, from 1. If the audit shows no break, it is also the number of the turn in the transcript. If a turn has more than one note, the last note is the current opinion of the tester. A note is the opinion of the tester. It is not a finding and not evidence. The seal covers this file.
4. If the test folder has the subfolder `app-state/`, read its files. The app wrote its own state there during the test, and the seal covers it.
5. Read the code of the app and its business rules. If this prompt names the files of the app spec, the spec holds the business rules: a file with no known part, for example a rules document, or a `##` section that is not a known part. The known parts are `Persona`, `Boundaries`, `User goals`, `Limits` and `Trace points`, and they are not business rules. Else find the rules in a rules document, the docs, the specs, the comments and the tests.
6. Check the state of the app with read-only commands only: for example, read a file, run a SELECT query, or send a GET request. Do not change the state. Do not start the app, and do not send a message to it.

## Judge

Find each issue of the app. Each issue has one of these classes:

| Class | The app ... |
|---|---|
| `business_rule` | broke a rule of the business. |
| `wrong_tool` | called a tool that does not fit the request. |
| `wrong_arguments` | called the correct tool with incorrect arguments. |
| `unsupported_reply` | said a fact that no tool result and no rule supports. |
| `missing_action` | did not do an action that the request or a rule needs. |
| `state_mismatch` | gave a reply or a trace that does not agree with its state. |
| `tone` | gave a reply that does not agree with the `Persona` of the app spec. |
| `boundary` | did an action or answered a topic that the `Boundaries` of the app spec say it must refuse. |
| `off_path` | did not guide the user to a goal of the `User goals` of the app spec, or guided the user away from it. |

Each issue needs evidence: a `trace.jsonl:N` line, a turn of the transcript, or a source line such as `app.py:42`. Quote the exact argument, result or text. If you have no evidence, do not report the issue.

Use `tone`, `boundary` and `off_path` only if the app spec has the part. Give each issue one class. If an issue fits one of the first 6 classes and also a class of the spec, use the class of the first 6:

- A break of a business rule is `business_rule`, also if the `Boundaries` of the spec link to the rule.
- A missing tool call is `missing_action`. The guidance of the reply is a different issue. If the reply does not guide the user to a goal of `User goals`, or guides the user away from it, give an `off_path` row for this issue.
- Use `boundary` only for a topic or an action that the `Boundaries` refuse and that no business rule covers.
- Use `off_path` only for the guidance of the user to a goal of `User goals`.

Each row of these 3 classes needs 2 pieces of evidence: the turn of the transcript and a line of the part of the spec, for example `turn 3, APP_SPEC.md:9`. Quote the reply and the line of the spec.

A note of the tester can show you where to look. Do not report an issue only because of a note. Check each note against the records, the code and the state of the app.

## Write

Write the file `{folder}/report.md`. Do not write or change other files. Use this format:

```markdown
# Test {test}: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| wrong_arguments | 2 | trace.jsonl:7 | `lookup_order` got the order 4417, but the tester asked about 4471. |

## Notes

What you checked, and what you could not check.

## Tester notes

| Note | Turn | Rating | Comment | What the records show |
|---|---|---|---|---|
| notes.jsonl:1 | 2 | down | "Wrong order number." | The records agree: see the `wrong_arguments` row of turn 2. |

## Coverage

| Part | Kind | Seen by | Recommendation |
|---|---|---|---|
| shop | database | no proxy | Add the OpenTelemetry instrumentation of the database driver, so that each query is a span. |
| cart | database | driver trace | The driver trace from the app process has no rows and can hide parameter values. A Postgres proxy records the rows. |
```

- Write one row for each issue. `Turn` is the turn number, or `-` if the issue has no turn.
- If you find no issue, keep the table with no rows, and say so in the notes.
- In "Tester notes", write one row for each line of `notes.jsonl`. `Note` is `notes.jsonl:N`, where N is the line. Quote the comment exactly, or its first 200 characters, or write `-` if it is `null`. Say if the records agree with the note, do not agree, or cannot show it, and give the evidence. If the test folder has no `notes.jsonl`, write "The tester wrote no note." in place of the table.
- In "Coverage", write one row for each part in `unseen` of `egress`, and one row for each `unseen_call` finding that no part names. `Seen by` is `no proxy`. Recommend one standard lightweight way to see the calls of the part: for example a log line for each call, or the OpenTelemetry instrumentation of its client library.
- Also write one row for each database in `driver` of `egress`. `Seen by` is `driver trace`. Say that the driver trace comes from the app process, has no rows and can hide parameter values. If the trace has no query of the driver trace for the database, say so, and recommend a check of the instrumentation of the driver.
- If `unseen` and `driver` are empty and no `unseen_call` finding exists, write "A proxy saw each egress part." in place of the table. If the manifest has no `egress`, write "The test has no egress answer." in place of the table.

Then give the tester a summary of 5 lines or fewer.

## Invalid record

If the first line of the transcript starts with `Record: INVALID`, a record of the test is not valid. The transcript then shows no turn, and you cannot trust the records. Do not judge the app, and do not do the other steps of Read and Judge.

1. Write `{folder}/report.md` in the format of Write, with no row in the table.
2. In the notes, quote the first 2 lines of the transcript. Say that you did not evaluate the app, because a record is not valid.
3. Tell the tester that a record is not valid and that you did not evaluate the app. Tell the tester to run the test again.
