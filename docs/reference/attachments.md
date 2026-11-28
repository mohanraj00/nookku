# Attachments and images

Release: nookku 0.6.1. Since 0.7.0 (not released yet): attachments in the records.

A message can have an attachment, for example a photo of a broken mug in a toy shop chat. This page tells you which surfaces carry an attachment to the agent, what the records keep, and what the [audit](glossary.md#audit) checks. [SPEC.md section 2.4](../../SPEC.md#24-attachments) gives the exact form.

## What the records keep

A row does not hold the bytes of an attachment. The `exchange` row of `tap.jsonl` and the `turn` row of `relay.jsonl` have the key `attachments`: for each attachment, its `media_type`, its size in `bytes` and its `sha256`. The bytes go in a side file next to the record:

```text
.nookku/tests/<test-id>/
  tap.jsonl
  tap.attachments/<sha256>
  relay.jsonl
  relay.attachments/<sha256>
```

A row with attachments has the version `"0.5"`. Nookku 0.6.x refuses this row and names the version, so an older audit cannot skip an image. A row with no attachment does not change. The [seal](glossary.md#seal) covers the side files, because it covers each file of the [test folder](glossary.md#test-folder).

## What the audit checks

The audit compares the attachments of each turn with the attachments of its exchange, in order. It also reads each side file and checks its SHA-256 and its size ([SPEC.md section 3.2](../../SPEC.md#32-matching), step 8).

| Class | What the records show |
|---|---|
| `altered_attachment` | The [tester](glossary.md#tester) sent one image, and the agent received a different image at that position. |
| `missing_attachment` | The turn has an attachment, and its exchange does not have it. |
| `extra_attachment` | The exchange has an attachment that the turn does not have. |
| `missing_attachment_file` | A row names an attachment, and its side file does not exist. |
| `altered_attachment_file` | The bytes of a side file do not have the SHA-256 or the size of its row. |

For example, in the case `attachment_side_file_altered`, one byte of the side file of the [tap](glossary.md#tap) changed. `nookku audit` prints:

```text
BREAK altered_attachment_file relay line -, tap line 1: attachment 1 (image/png, 72 bytes, sha256 99f2ab298058): the side file tap.attachments/99f2ab2980589ba64226149678211f2870a591e63540320a961030867cd4c5c4 is altered, it has 72 bytes, sha256 e661d1174b18
1 turns, 1 exchanges, 0 blocked model calls, 0 model sessions, 1 breaks
Result: breaks found (exit 1)
```

The conformance cases `attachment_*` in [`conformance/cases/`](../../conformance/cases/) give each class.

## Surfaces

I checked each surface without a model prompt and without a Codex job: the hook input schema of the installed CLI, the hook code of the plugin, and the plugin proof.

| [Harness](glossary.md#harness) | Surface | Can it carry an attachment? | State |
|---|---|---|---|
| Claude Code 2.1.319 | Command hook `UserPromptSubmit` (the [relay](glossary.md#relay) of the plugin and of the [project hooks](glossary.md#project-hooks)) | No. The input has only the text of the prompt. | Not supported. The plugin drops a prompt with an attachment in [relay mode](glossary.md#relay-mode) ([load.json](../../proofs/plugin/load.json), [method](../../scripts/proof_plugin_load.py)). |
| Claude Code 2.1.319 | Function hook `prompt.submit` (the display layer of the plugin) | Yes. The event has `attachments`. | Not supported. The display layer holds no relay rule ([ADR 0001](../contributing/adr/0001-one-core-one-plugin.md)). A capture path there needs a new relay path in TypeScript, so I did not build it. |
| Codex 0.169.0 | Command hook `UserPromptSubmit` | No. The schema `user-prompt-submit.command.input` has `prompt` as the only message field, and `additionalProperties: false`. | Not supported. The relay sends the text, and the agent does not get the image. |
| Nookku | Chat page | No. The page sends text only. | Not supported. |
| Nookku | [Scripted test](glossary.md#scripted-test) | No. A script message is a text. | Not supported. |
| Nookku | HTTP tap, adapter `openai` | Yes. An `image_url` part with a base64 `data:` URL. | Supported. The tap writes the side file before it sends the request to the agent. If it cannot write the side file, it answers 502 and sends nothing. |

Thus no relay writes attachments yet. If an agent gets an image through the tap, and the relay sent no image, the audit gives `extra_attachment`. The `json` adapter and the stdio tap do not capture attachments.

[limits.md](../limits.md) lists this limit.
