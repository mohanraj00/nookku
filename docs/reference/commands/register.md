# `nookku register`

Release: nookku 0.7.0.

```text
nookku register [--root PATH] [--file PATH] [--json]
```

Check an egress answer and keep it for the next start ([SPEC.md section 7.11](../../../SPEC.md#711-egress-discovery)). The [harness model](../glossary.md#harness-model) runs it after the prompt `nookku start`, with the answer in `.nookku/egress.json` and `--file .nookku/egress.json`. You can also run it in a shell. The answer is a JSON object on standard input, or in the file of `--file`, with the 5 lists `model_apis`, `backends`, `mcp_servers`, `databases` and `other`. If the answer does not obey the rule, `register` writes nothing, prints the error and exits with 1. Else it writes `.nookku/discovery.json` and prints one line for each part. A start takes the answer in the next 30 minutes ([`FRESH`](../../../src/nookku/discovery.py)). The answer holds the names of the variables, never their values: `register` refuses a URL with a user, a password or a secret query value.

```bash
nookku register <<'EOF'
{"model_apis": [{"api": "anthropic", "env": "ANTHROPIC_BASE_URL", "url": null}],
 "backends": [{"name": "stock", "env": "STOCK_URL", "url": "http://127.0.0.1:9001"}],
 "mcp_servers": [], "databases": [], "other": []}
EOF
```

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | the current folder | The project. |
| `--file PATH` | standard input | The file of the answer. |
| `--json` | off | Print `registered` and `parts`, or `error`, as JSON. |

| Exit code | Meaning |
|---|---|
| 0 | The answer is kept. |
| 1 | The answer does not obey the rule. Nothing was written. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku register <<<'{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}'
```

```text
nookku: the egress answer is registered. The next start uses these parts:
- no egress part: the agent calls no service
Show these parts to the tester. If they are correct, the tester types the prompt nookku start in the next 30 minutes. If a part is wrong, run nookku register again with the correct answer.
```
