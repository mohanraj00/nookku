# `nookku view`

Release: nookku 0.6.2.

Print each relayed turn. Both forms of the [relay](../glossary.md#relay) use it to show each reply in a second terminal. With an [entry](../glossary.md#entry), it shows the turns of the latest test, and it follows to the next test. With no entry and no `--record`, it shows the configured record, and it reads the config again before each poll. If the config gives a different record, the view prints `════ record <path> ════` and follows that record. When the config gets an entry, the view follows each test from that time. You can start the view before `nookku init`.

If the [relay record](../glossary.md#relay-record) has an invalid line, `view` shows the error with the file and the line on stderr. Without `--no-follow`, it shows the error one time and continues to wait. When the record changes and is valid, it shows the next turns. With `--no-follow`, it stops with exit code 2. If the record does not start with the turns that the view showed, for example because a person removed a line, the view prints `──── the record changed: the view shows each turn again ────` and shows each turn again from turn 1. A test has no relay record before its first turn, so the view of such a test shows no turn and exits with 0. After the end of a test, `nookku verify` shows a record that is missing.

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--no-follow` | off | Print the turns so far and stop. Without it, `view` waits for new turns until you stop it. |
| `--record FILE` | from the config | The relay record to show. |
| `--text` | on | The text view for a terminal. It is the only view of `nookku view` now. The chat page is [`nookku chat`](chat.md). |

| Exit code | Meaning |
|---|---|
| 0 | The view stopped. |
| 2 | The config cannot be read. With `--no-follow`: the relay record is invalid, or, with no entry, the configured record does not exist. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku view --no-follow --text
```

```text
════ test 20261127-194216-71f9 ════
──── script, turn 1 ────
What is your refund policy?
──── agent ────
Our refund policy:

1. Damaged items: full refund.
2. Change of mind: 30 days.

──── script, turn 2 ────
Do you ship to Pune?
──── agent ────
We ship to Chennai and Pune. Delivery takes 3 to 5 days.  
──── script, turn 3 ────
What is the price of the blue mug?
──── agent ────
| item | price |
|---|---|
| blue mug | € 8 |
| teapot | € 24 |
```
