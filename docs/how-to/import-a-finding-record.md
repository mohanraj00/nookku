# Import a finding record into another test suite

A [finding record](../reference/glossary.md#finding-record) is one confirmed defect of your agent, as one JSON object. This page shows how another tool reads a record and makes a regression case from it. [SPEC.md section 10](../../SPEC.md#10-finding-record) gives each field and each rule.

The record is self-contained. The other tool needs no [test folder](../reference/glossary.md#test-folder), and it does not have to import Nookku.

## 1. Confirm a defect

A record comes from a defect that a person confirmed:

- For a mismatch with the answer key ([SPEC.md section 7.17](../../SPEC.md#717-answer-key)), run [`nookku adjudicate`](../reference/cli.md#nookku-adjudicate) with the outcome `agent_wrong`.
- For an issue of the [evaluation](../reference/glossary.md#evaluation), run [`nookku evaluation add`](../reference/cli.md#nookku-evaluation). A row of a person is confirmed. A model row is not confirmed, and it is in the export only with `--model-rows`.

## 2. Export the records

For one test, give the digest of the tested thing, for example an image digest or a commit:

```bash
nookku finding export 20261120-101500-a1b2 --subject sha256:ab12cd34 > findings.jsonl
```

For a [gate run](gate-a-release.md), the subject is the subject of the gate run:

```bash
nookku finding export --gate gate-20261120-101400-9f8e7d6c > findings.jsonl
```

The output has one record on each line. The command prints no record if the [seal](../reference/glossary.md#seal) of a test is not intact.

## 3. Check the records

```bash
nookku finding check findings.jsonl
```

The command exits with 0 if each line is a valid record. A tool that does not have Nookku uses the JSON Schema for the form of a record. `nookku finding schema` prints it, and the package has it as `nookku/finding_record.schema.json`. The schema does not check the seal digest. The reader below does that check with the standard library.

## 4. Read a record in the other tool

This reader uses only the Python standard library. It refuses a record of another major version, and it ignores each field that it does not know. Do the same in another language.

```python
import hashlib
import json


def read_finding(line: str) -> dict:
    """One finding record of major version 1, or ValueError."""
    record = json.loads(line)
    if record.get("record") != "nookku.finding":
        raise ValueError("not a finding record")
    major = str(record.get("version", "")).split(".")[0]
    if major != "1":
        raise ValueError(f"unknown major version: {record.get('version')!r}")
    seal = record["seal"]
    digest = hashlib.sha256(seal["text"].encode("utf-8")).hexdigest()
    if digest != seal["sha256"]:
        raise ValueError("the seal digest does not match the seal text")
    sealed = json.loads(seal["text"])["files"]
    for name, sha in seal["files"].items():
        if sealed.get(name) != sha:
            raise ValueError(f"the seal does not cover {name}")
    return record


def regression_case(record: dict) -> dict:
    """The messages to send, and the check of the last reply."""
    turn = record["turn"]
    messages = record["script"]["messages"]
    return {
        "name": record["id"],
        "messages": messages if turn is None else messages[: turn["number"]],
        "expected": record["expected"],
        "issue": record["issue"],
        "origin": {"subject": record["subject"], "seal": record["seal"]["sha256"]},
    }
```

A regression case from a record:

- **The input.** Send `script.messages` from message 1 to message `turn.number`, in order. Each message is the text that the agent received, byte for byte.
- **The expected result of a mismatch.** `expected` gives the value and the rule. With the match `exact`, the value at `expected.field` in the JSON of the last reply must be the string `expected.value`. With `number`, the difference from `expected.value` must be `expected.tolerance` or less. Compare decimal numbers, not binary floats. An empty `field` means the full reply text.
- **The expected result of an issue row.** `expected` is `null`. `issue.text` says what was wrong, in the words of the person. Write the check by hand from that text.
- **The origin.** Keep `id`, `subject`, `adjudication` and `seal.sha256` with the case. They show which version had the defect, who confirmed it, and which sealed test is the evidence.

## 5. Pin the version

The format has a version, `<major>.<minor>`. A new minor version only adds fields, so a reader of `1.0` reads `1.7`. A new major version can change a field, so the reader above refuses it. Pin a release of Nookku in the other tool, and run the cases of [`conformance/finding/`](../../conformance/finding/) against your reader: each case gives a record and the expected result.

## Limits

- The record shows that it agrees with its own seal text. It does not show that the test folder is unchanged. A reader with the test folder runs [`nookku verify`](../reference/cli.md#nookku-verify).
- The subject is the text that the caller gave. Compare it with the digest that you expect.
- `observed` has 200 characters at most. `turn.reply` has the full reply.
