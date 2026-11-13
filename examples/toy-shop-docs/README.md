# Toy shop docs agent

This toy shop support agent retrieves a section of a local store and cites its locator. It uses the Python standard library only, and it has no model. It is the example of [docs/how-to/gate-a-ci-job.md](../../docs/how-to/gate-a-ci-job.md).

- [agent.py](agent.py) speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)). The reply is JSON text with `answer` and `source`. `source` is the locator of the section: the path of a store file, `#`, and the heading of the section.
- [store/](store/) holds the 2 store files.
- [APP_SPEC.md](APP_SPEC.md) declares the answer key and the `Verdict` table.
- [keys/sources.json](keys/sources.json) is the answer key: the locator that each question of the script must cite.
- [script.jsonl](script.jsonl) is the script of 3 messages.

## Run it

From a copy of this folder, run these commands:

```bash
nookku init plugin --entry "python3 agent.py" --spec APP_SPEC.md
```

```bash
echo '{"model_apis": [], "backends": [], "mcp_servers": [], "databases": [], "other": []}' | nookku register
```

```bash
nookku run --script script.jsonl --verdict --no-evaluate
```

The last command exits with 0. If the agent cites a wrong section, the verdict is `fail` and the command exits with 1.
