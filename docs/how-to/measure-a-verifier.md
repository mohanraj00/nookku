# Measure a verifier on seeded false claims

Release: nookku 0.6.1. Since 0.7.0 (not released yet): the command `nookku verifier`.

Use `nookku verifier run` to measure which claims a verifier refutes. Give it claims you know are true and seeded claims you know are false. Mark the false claims with `seeded: true` in the claim set. The verifier receives the ID and text of each claim. Nookku uses `seeded` to score the reply. See the [claim set and protocol](../../SPEC.md#11-verifier-measurement).

## Run the toy shop example

Open the [toy shop example folder](../../examples/toy-shop-verifier/). Create `.nookku/config.json` there with this content.

```json
{"entries": {"stock": ["python3", "stock_verifier.py"]}}
```

Run the verifier from that folder.

```sh
nookku verifier run claims.json --entry stock
```

The [stock verifier](../../examples/toy-shop-verifier/stock_verifier.py) uses an old stock count for the kite. It supports the false claim with the old count and refutes the true claim with the current count. The report gives [2 of 3](../../tests/test_verifier.py#L45) for the refutation rate and [1 of 5](../../tests/test_verifier.py#L46) for the false refutation rate. The [claim set](../../examples/toy-shop-verifier/claims.json) gives the text and expected truth value of each claim.

## Read the report

- `refutation_rate` divides the number of seeded false claims refuted by the total number of seeded false claims.
- `false_refutation_rate` divides the number of true claims refuted by the total number of true claims.
- `errors` counts the claims with a start failure, an invalid reply, a failed exit or a timeout. These claims stay in their group totals. Only `refuted` increases a numerator. A rate is `null` when its group is empty.

The rates apply to this claim set and this verifier version. The report identifies the claim set by source, version and SHA-256. Keep the verifier version with the report if you compare runs. A verifier that uses a model can give different replies on the same input. The [entry](../reference/glossary.md#entry) owns all model calls. The report gives a measurement outside the gate verdict.
