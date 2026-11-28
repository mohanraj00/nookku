# `nookku verifier`

Release: nookku 0.6.2. Since 0.7.0 (not released yet): the command `nookku verifier`.

```text
nookku verifier run CLAIMS --entry NAME [--out FILE] [--root PATH] [--timeout SECONDS]
```

Measure a verifier on a declared claim set. The report records each verdict and gives the fraction of seeded false claims refuted and the fraction of true claims refuted. Each fraction has a numerator and a denominator. Errors have their own count and stay in the group totals. The measurement applies to this claim set and verifier version. A model verifier can give different replies across runs. See the [method and toy shop example](../../how-to/measure-a-verifier.md) and the [file formats](../../../SPEC.md#11-verifier-measurement).

| Argument | Default | Meaning |
|---|---|---|
| `COMMAND` | required | `run`. |

`run` takes these arguments.

- `CLAIMS` gives the declared JSON claim set. It is required.
- `--entry NAME` selects a name in the config key `entries`. It is required.
- `--out FILE` gives the report path. The default is `verifier.json` beside `CLAIMS`.
- `--root PATH` gives the project folder with `.nookku/config.json`. The default is the current folder.
- `--timeout SECONDS` gives the maximum time for each claim. The default is [240 seconds](../../../src/nookku/stdio.py#L27).

| Exit code | Meaning |
|---|---|
| [0](../../../src/nookku/cli.py) | The command wrote the report, also if some claims gave errors. |
| [2](../../../src/nookku/cli.py) | The command cannot use the claim set or the config, or cannot write the report. |

## Example

In a copy of `examples/toy-shop-verifier/`, with `.nookku/config.json` that holds `{"entries": {"stock": ["python3", "stock_verifier.py"]}}`:

```bash
nookku verifier run claims.json --entry stock
```

```text
nookku: wrote verifier.json
```
