# `nookku policy`

Release: nookku 0.6.1.

```text
nookku policy [set KEY VALUE] [--root PATH]
```

Print each key of the [policy file](../glossary.md#policy-file) `.nookku/policy.json` with its value, as JSON. With `set`, change one key, then print the keys. Only a person runs this command, in a shell. The [relay](../glossary.md#relay) denies it from the model ([SPEC.md section 7.9](../../../SPEC.md#79-policy-file)). [config.md](../config.md#nookkupolicyjson) explains the file.

| Argument or flag | Default | Meaning |
|---|---|---|
| `ACTION` | none | `set` changes one key. With no action, the command only prints the keys. |
| `KEY` | | The key to change. |
| `VALUE` | | The new value of the key. |
| `--root PATH` | the current folder | The project. |

| Exit code | Meaning |
|---|---|
| 0 | The keys were printed. With `set`, the key was changed first. |
| 1 | The policy file is not valid, the key is not known, or the value is not valid. The text names the cause. Nothing was changed. |
| 2 | The arguments are not complete. |

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`:

```bash
nookku policy
```

```text
{
 "answer_keys": [],
 "control_distance": 2,
 "guard_fields": [
  "path",
  "file_path",
  "url",
  "uri",
  "command"
 ],
 "guard_reads": [],
 "scripts": "person"
}
```
