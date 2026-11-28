# `nookku audit`

Release: nookku 0.6.1.

Compare the [relay record](../glossary.md#relay-record) with the [tap record](../glossary.md#tap-record) ([SPEC.md section 3](../../../SPEC.md#3-audit)).

| Flag | Default | Meaning |
|---|---|---|
| `--tap FILE` | required | The tap record. |
| `--relay FILE` | required | The relay record. |
| `--json` | off | Print the report as JSON. The [bridge](../glossary.md#bridge) writes this form to `audit.json`. |
| `--script FILE` | none | The script of a [scripted test](../glossary.md#scripted-test). The [audit](../glossary.md#audit) also compares the relay record with it ([SPEC.md section 3.2](../../../SPEC.md#32-matching), step 7). |

| Exit code | Meaning |
|---|---|
| 0 | The records are valid and have no [break](../glossary.md#break). |
| 1 | The records are valid and have one or more breaks. |
| 2 | A record is missing or invalid, or the [tap](../glossary.md#tap) has an unparsed exchange. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku audit --tap .nookku/tests/20261127-194213-41bc/tap.jsonl --relay .nookku/tests/20261127-194213-41bc/relay.jsonl
```

```text
3 turns, 3 exchanges, 0 blocked model calls, 0 model sessions, 0 breaks
Result: clean (exit 0)
```
