# `nookku export`

Release: nookku 0.6.2.

```text
nookku export [TEST] [--root PATH] [--tests-dir PATH] [--out FILE]
```

Write a test as one HTML file, so you can give it to a person who does not have the project or nookku. The file holds the CSS, the script and the data inline. It shows the chat, the [trace](../glossary.md#trace) steps, the notes, the [audit](../glossary.md#audit) result and the [seal](../glossary.md#seal) state ([SPEC.md section 5](../../../SPEC.md#5-relays)).

- The file loads nothing from the network. A link or a web image shows as text with its URL.
- The file runs no script and no HTML from the agent. It holds no page URL and no page token.
- An image or a video file that a reply names with a Markdown link or image goes into the file, with the file rule of the chat page. A path in the text of a reply adds no file. If a reply names a file only in code, the file shows it in a list at its end. A file larger than [4 MiB](../../../src/nookku/export.py#L41-L44), or a file after a sum of 32 MiB, shows as its path. These limits are chosen values, not measurements.
- The command reads the test and changes no record. It does not write into `.nookku/`, into a [test folder](../glossary.md#test-folder) or into the seal home.
- On a system that cannot open a file relative to a folder (Windows), the command writes nothing and exits with 1. Use the "Export" button of the chat page there.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the test folder. |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--out FILE` | `<test id>.html` in the current folder | The HTML file to write. |

| Exit code | Meaning |
|---|---|
| 0 | The file was written. |
| 1 | The command must not write to the path, for example a path in `.nookku/` or a link, or it cannot write the file. |
| 2 | No test folder. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku export 20261127-194213-41bc --out shop-test.zip
```

```text
Wrote test 20261127-194213-41bc to ~/shop/shop-test.zip
```
