# Evaluate test {test}

The tester ended test {test} of the app in this project. Evaluate the app. Use only the records of the test, the project files and read-only commands. You did not see the conversation while the tester talked, so judge the record, not your memory.

The test folder is `{folder}`.

## Read

1. Run `nookku transcript --trace --test {test}`. Its first line says if a record changed after the end of the test. If the seal is broken, say so in the notes, and do not trust the changed files. Then the transcript shows each turn as the app received it and sent it. Under each turn, it shows the model items of the app: the messages, the tool calls with their input and result, and the commands.
2. Read `findings.json` and `audit.json` in the test folder. A finding is a fact, not yet an issue. The audit shows if the words of a turn changed between the tester and the app.
   To read a file of the test folder in a shell, use `cat`, `sed -n`, `jq` or `grep`. The relay denies other commands that name `.nookku`.
3. Read the code of the app and its business rules: for example a rules document, the docs, the specs, the comments and the tests.
4. Check the state of the app with read-only commands only: for example, read a file, run a SELECT query, or send a GET request. Do not change the state. Do not start the app, and do not send a message to it.

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

Each issue needs evidence: a `trace.jsonl:N` line, a turn of the transcript, or a source line such as `app.py:42`. Quote the exact argument, result or text. If you have no evidence, do not report the issue.

## Write

Write the file `{folder}/report.md`. Do not write or change other files. Use this format:

```markdown
# Test {test}: evaluation

| Class | Turn | Evidence | Issue |
|---|---|---|---|
| wrong_arguments | 2 | trace.jsonl:7 | `lookup_order` got the order 4417, but the tester asked about 4471. |

## Notes

What you checked, and what you could not check.
```

- Write one row for each issue. `Turn` is the turn number, or `-` if the issue has no turn.
- If you find no issue, keep the table with no rows, and say so in the notes.

Then give the tester a summary of 5 lines or fewer.
