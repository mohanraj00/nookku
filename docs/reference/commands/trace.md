# `nookku trace`

Release: nookku 0.6.1.

```text
nookku trace [TEST] [--root PATH] [--tests-dir PATH] [--json] [--verdict] [--egress FILE] [--ingress FILE] [--otlp-file FILE] [--otlp-endpoint URL] [--openinference FILE] [--gateway SOURCE --key-alias ALIAS [--key-alias ALIAS] [--gateway-tag TAG] [--gateway-skew SECONDS]]
```

Build the [trace](../glossary.md#trace) of a test again, and show its [findings](../glossary.md#findings) ([SPEC.md section 8](../../../SPEC.md#8-trace)). The findings show in groups by turn, and each control character of a finding shows as its escape ([read the results](../../how-to/read-the-results.md#4-read-the-findings)). It also writes `performance.json` ([SPEC.md section 8.7](../../../SPEC.md#87-performance)) and `verdict.json` ([SPEC.md section 7.14](../../../SPEC.md#714-verdict)) again. It shows the verdict if the app spec gives limits, if the verdict is `fail`, or with `--verdict`. If the test has a [seal](../glossary.md#seal), it rebuilds only from sources that agree with the seal.

| Argument or flag | Default | Meaning |
|---|---|---|
| `TEST` | the latest test | The test id, or the path of the [test folder](../glossary.md#test-folder). |
| `--root PATH` | the current folder | The project. |
| `--tests-dir PATH` | `$NOOKKU_TESTS_DIR`, else `.nookku/tests` | The [tests folder](../cli.md#the-tests-folder). |
| `--json` | off | Print `findings.json`. |
| `--verdict` | off | Exit with 1 if the verdict is `fail`. Use it in CI. |
| `--egress FILE` | none | The Koodam egress spans of the test. The trace checks the file, copies it into the test folder as `egress.jsonl`, adds it to the seal and gives the findings `egress_not_in_discovery` and `egress_denied` ([SPEC.md section 8.8](../../../SPEC.md#88-egress-spans)). |
| `--otlp-file FILE` | none | Write the test as OTLP trace JSON outside the test folder. |
| `--otlp-endpoint URL` | none | Send the test to an OTLP/HTTP trace endpoint as protobuf. |
| `--openinference FILE` | none | Compare app spans in an export with the proxy records ([SPEC.md section 8.10](../../../SPEC.md#810-openinference-spans)). |
| `--ingress FILE` | none | The ingress spans of your app for the test: 1 JSON line for each request, with a time, a status and an outcome. The trace checks the file, copies it into the test folder as `ingress.jsonl`, adds it to the seal and writes the counts to the key `ingress` of `findings.json`. A span has no body and no path, so it adds no finding and does not replace a row of `tap.jsonl` ([SPEC.md section 8.12](../../../SPEC.md#812-ingress-spans)). |
| `--gateway SOURCE` | none | Read the model calls of the app from the spend logs of a LiteLLM gateway: a file, or the URL of the gateway API. For a URL, put a key that can read the spend logs in `NOOKKU_GATEWAY_KEY`. The URL must be `https`, or `http` to this computer ([SPEC.md section 8.9](../../../SPEC.md#89-gateway-logs)). |
| `--key-alias ALIAS` | none | Keep the logs of this key alias, for example the `kd-<agent uid>` alias of a Koodam Agent. Give it 1 or more times. `--gateway` needs it. |
| `--gateway-tag TAG` | none | Also keep only the logs with this request tag. |
| `--gateway-skew SECONDS` | 0 | The clock of the gateway minus the clock of this computer, from -86400 to 86400. For example, if the gateway clock is 2.5 seconds ahead, give `2.5`. The trace moves each gateway time by this value before it keeps the logs of the test window and before it matches a gateway call to a model API call ([SPEC.md section 8.9](../../../SPEC.md#89-gateway-logs)). `--gateway` needs it. |

If a model API proxy and the gateway both record a call of the app, the trace keeps 1 item for it, and `performance.json` counts it 1 time. The match rule is in [SPEC.md section 8.9](../../../SPEC.md#89-gateway-logs).

| Exit code | Meaning |
|---|---|
| 0 | The trace was built. With `--verdict`, the verdict is also `pass`. |
| 1 | Only with `--verdict`: the trace was built, and the verdict is `fail`, or `verdict.json` was not written. |
| 2 | No test folder with a manifest, the seal is broken, a record is not valid, or the egress file or the ingress file cannot be read or has a span of a later version, or the gateway logs were not read. The trace was not rebuilt. Also, the OTLP export failed: then the trace was rebuilt, and the command printed it and the verdict before the error. |

If your agent runs in a Koodam Workspace, export the egress spans outside the pod for the time of the test. Then give them to the trace:

```sh
koodam trace shop --json --since 2026-10-23T09:00:00Z --until 2026-10-23T10:00:00Z > spans.jsonl
nookku trace --egress spans.jsonl
```

The trace uses only the spans from `started` to `ended` of the manifest, so a wider export window is not a problem.

To compare app spans with the independent proxy records, export the test window and run:

```bash
nookku trace TEST --openinference spans.json
```

In Phoenix, use `client.spans.get_spans_dataframe(project_name=..., start_time=..., end_time=...)` and write the result with `to_json(orient="records", date_format="iso")`. For Langfuse, request the observations of the test window with the `core,basic,metadata,model` fields and combine all pages into one JSON array. OTLP trace JSON is also accepted. [Phoenix export](https://arize.com/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/extract-data-from-spans), [Langfuse observations](https://langfuse.com/docs/api-and-data-platform/features/observations-api), [match rule](../../../SPEC.md#810-openinference-spans).


## Export to an OTLP collector

Use the test of a toy shop to try the export.

```bash
nookku trace TEST --otlp-file toy-shop-traces.json
nookku trace TEST --otlp-endpoint http://127.0.0.1:6006/v1/traces
```

The second command sends the test to a local Phoenix server. In Phoenix, open the default project and select the test trace. If the server requires an API key, set `OTEL_EXPORTER_OTLP_TRACES_HEADERS` to `Authorization=Bearer%20<key>`. For an isolated local container, set `PHOENIX_ENABLE_AUTH=false` and publish the port on loopback.

For a local Langfuse server, set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` to the keys for the test project. Run:

```bash
token=$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 | tr -d '\n')
OTEL_EXPORTER_OTLP_TRACES_HEADERS="Authorization=Basic%20$token" \
  nookku trace TEST --otlp-endpoint http://127.0.0.1:3000/api/public/otel/v1/traces
```

Open the test trace in the Langfuse project. The trace ID is in `traceId` of the spans in the OTLP JSON file.

Use the full trace endpoint URL for a hosted service. The header variable is a comma-separated list of `name=value` [entries](../glossary.md#entry). Put credentials in the environment. [Phoenix trace setup](https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing), [Langfuse OTLP setup](https://langfuse.com/docs/opentelemetry/get-started).

## Example

In a copy of the toy shop folder `examples/toy-shop/` of this repo, in the project `~/shop`: The test `20261127-194213-41bc` is a test of `nookku run`.

```bash
nookku trace 20261127-194213-41bc
```

```text
Trace: 0 model items in 3 turns, no findings.
File: ~/shop/.nookku/tests/20261127-194213-41bc/trace.jsonl
```
