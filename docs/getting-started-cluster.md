# Get started in a cluster

In this tutorial, you test the toy shop agent in a Kubernetes cluster. The agent runs behind a Service. Claude Code runs in a [Koodam](https://github.com/mohanraj00/koodam) Workspace with traced egress and the Nookku preset. You run a test with 3 messages, give the egress spans of the test to the [trace](reference/glossary.md#trace), and start the [evaluation](reference/glossary.md#evaluation).

The Nookku preset of Koodam v0.5.0 gives the Workspace pod the pinned Nookku 0.6.0, the [plugin](reference/glossary.md#plugin) files and a [test folder](reference/glossary.md#test-folder) on the home volume. It does not load the plugin in the [harness](reference/glossary.md#harness). It has 2 gaps, and step 4 of this page closes them ([koodam#476](https://github.com/mohanraj00/koodam/issues/476), [koodam#478](https://github.com/mohanraj00/koodam/issues/478)).

The values on this page come from one run of [scripts/proof_cluster.py](../scripts/proof_cluster.py) on 2026-11-27, on macOS, in a kind cluster, with Koodam v0.5.0 and Claude Code 2.1.319 ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), [records](../proofs/cluster/plugin-claude-code-no-evaluation/)). That run did steps 1 to 8 with the mock model of the bundled gateway and no login, so it has no evaluation. The script does each step of this page with `kubectl exec`, and gives each prompt to `claude -p` in the pod. The test id and the times are different on your cluster.

This page does not cover Codex in a Workspace. The last Codex proof used Koodam 0.3.0 and wrote no report ([Limits](#limits)).

If you do not know Nookku, do [Get started](getting-started.md) first. It explains the [audit](reference/glossary.md#audit), the [findings](reference/glossary.md#findings) and the report.

## What you need

- A Kubernetes cluster. The proof used kind ([versions](../proofs/cluster/plugin-claude-code-no-evaluation.json)).
- `kubectl`, `helm` and the `koodam` CLI 0.5.0 ([release](https://github.com/mohanraj00/koodam/releases/tag/v0.5.0)).
- A Workspace image with `python3` 3.11 or later. The default Workspace image of Koodam has no Python, and the preset needs it. Step 3 builds one.
- For the evaluation only: a Claude subscription for `claude setup-token`.
- A clone of this repo, for the toy shop agent and its [entry](reference/glossary.md#entry):

  ```bash
  git clone https://github.com/mohanraj00/nookku.git
  cd nookku
  ```

If you use kind on Docker Desktop, keep 1.2 GB free on the disk of Docker after the install. A full disk stops each container of Docker, also the containers of other projects. The proof stops if the node has less than 1200 MB free ([method](../scripts/proof_cluster.py)).

## 1. Install Koodam with the egress proxy and the Nookku image

Find the address and the port of the API server. The NetworkPolicy of the proxy needs them:

```bash
kubectl get endpointslices -n default -l kubernetes.io/service-name=kubernetes \
  -o jsonpath='{.items[0].endpoints[0].addresses[0]} {.items[0].ports[0].port}'
```

Write `values.yaml`. Put the address and the port of the API server in `apiServer`. The `extraEgress` rule lets the Workspace pods call the toy shop Service directly, with no proxy. `nookku.image` is the Nookku data image of the Koodam release `v0.5.0`. The chart needs a digest in this reference:

```yaml
nookku:
  image: ghcr.io/mohanraj00/koodam-nookku@sha256:be6c674c2699532e3d2b94a89a96b3ad7ea9b92ac0e694459987e1fe2e9d2a2e
gateway:
  mode: bundled
  masterKeySecret:
    name: koodam-gateway
    key: master-key
  bundled:
    mock:
      enabled: true
      modelName: mock-1
      response: "mock answer"
    postgres:
      persistence:
        enabled: false
egressProxy:
  enabled: true
  clusterIP: 10.96.100.100
  replicas: 1
  networkPolicy:
    apiServer:
      - to:
          - ipBlock:
              cidr: <API server address>/32
        ports:
          - protocol: TCP
            port: <API server port>
workspace:
  networkPolicy:
    namespaces: [dev-shop]
    extraEgress:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: shop
            podSelector:
              matchLabels:
                app: toy-shop
        ports:
          - protocol: TCP
            port: 8080
```

`10.96.100.100` is a free address in the Service range of kind (`10.96.0.0/16`). On another cluster, use a free address in its Service range.

The bundled gateway with its mock model gives the harness a model route with no model key and no login. The mock model cannot evaluate a test. For the evaluation, use the login of step 5.

Install the chart. The reference has the version and the digest of the chart:

```bash
kubectl create namespace koodam-system
kubectl create namespace shop
kubectl create namespace dev-shop
kubectl -n koodam-system create secret generic koodam-gateway \
  --from-literal=master-key="sk-$(openssl rand -hex 32)"
helm install koodam \
  oci://ghcr.io/mohanraj00/charts/koodam:0.5.0@sha256:746593cfa80ee90bf4a4244d64aba072ce5cd1c8bc3ae720a0d2f1357e6032f2 \
  -n koodam-system -f values.yaml --wait --timeout 10m
```

The chart gives `--nookku-image` to the controller from `nookku.image`.

## 2. Run the toy shop agent behind a Service

The toy shop HTTP agent listens on `127.0.0.1` by default. In a pod, give it `0.0.0.0`, so that the Service can reach it:

```bash
kubectl -n shop create configmap toy-shop \
  --from-file=examples/toy-shop/agent.py --from-file=examples/toy-shop/http_agent.py
kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: toy-shop
  namespace: shop
spec:
  replicas: 1
  selector:
    matchLabels:
      app: toy-shop
  template:
    metadata:
      labels:
        app: toy-shop
    spec:
      containers:
        - name: app
          image: python:3.13-alpine
          command: ["python3", "-u", "/app/http_agent.py", "8080", "0.0.0.0"]
          ports:
            - containerPort: 8080
          readinessProbe:
            tcpSocket:
              port: 8080
          volumeMounts:
            - name: app
              mountPath: /app
      volumes:
        - name: app
          configMap:
            name: toy-shop
---
apiVersion: v1
kind: Service
metadata:
  name: toy-shop
  namespace: shop
spec:
  selector:
    app: toy-shop
  ports:
    - port: 8080
EOF
kubectl -n shop rollout status deployment/toy-shop
```

## 3. Make the Workspace with the Nookku preset

Build a Workspace image with `python3` 3.11 or later. This `Dockerfile` adds the `python3` of Debian to the Workspace image of the release:

```dockerfile
FROM ghcr.io/mohanraj00/koodam-workspace:0.5.0@sha256:b4f428400d0bda4e8698b92bcc12111e1f25213ea6ce4c6a804c787ec566180a
USER 0:0
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'
USER 1000:1000
```

Build the image and give it to the nodes. On kind:

```bash
docker build -t nookku-proof/workspace-python:0.5.0 .
kind load docker-image nookku-proof/workspace-python:0.5.0 --name <cluster>
```

On another cluster, push the image to a registry that the cluster can read.

Then make the Workspace. `plugins: [nookku]` selects the preset for the harness:

```bash
kubectl label namespace dev-shop koodam.dev/profile=nookku-proof
kubectl apply -f - <<'EOF'
apiVersion: core.koodam.dev/v1alpha1
kind: Profile
metadata:
  name: nookku-proof
spec:
  namespaces: [dev-shop]
---
apiVersion: core.koodam.dev/v1alpha1
kind: Workspace
metadata:
  name: shop
  namespace: dev-shop
spec:
  storage: 5Gi
  image: nookku-proof/workspace-python:0.5.0
  gateway:
    model: mock-1
    budgetPerDay: "1"
  harnesses:
    - name: claude-code
      version: 2.1.319
      plugins: [nookku]
EOF
kubectl -n dev-shop wait workspace/shop --for=jsonpath='{.status.phase}'=Running --timeout=600s
kubectl -n dev-shop get workspace shop \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {end}'
```

In the proof, the Workspace was `Running`, with `TracedEgress=True` and `Harnesses=True`. The init containers `koodam-nookku-python` and `koodam-nookku-files` of the preset ended with exit code 0 ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W1).

## 4. Put Nookku on the PATH in the Workspace

Open a login shell in the Workspace pod. Do the next commands of this step in that shell:

```bash
kubectl -n dev-shop exec -it shop-0 -c workspace -- bash -l
```

The preset gives these files. They are read-only:

- `/koodam/bin/nookku`: the launcher of the pinned Nookku.
- `/koodam/nookku/lib`: the pinned Nookku 0.6.0.
- `/koodam/nookku/plugin`: the plugin files of the Nookku tag `v0.6.0`.

A login shell exports `NOOKKU_TESTS_DIR=/home/dev/nookku-tests`. This folder is on the home volume, with mode 0700, so the tests stay after the pod stops. You do not set the test folder. To use another folder, give `--tests-dir PATH` to the command, or set `NOOKKU_TESTS_DIR` ([reference/cli.md](reference/cli.md)).

Koodam v0.5.0 has 2 gaps:

- A login shell does not have `/koodam/bin` on the PATH ([koodam#476](https://github.com/mohanraj00/koodam/issues/476)).
- The launcher gives the pinned lib only to its own process. Nookku starts its [bridge](reference/glossary.md#bridge) in a new Python process, so `nookku start` fails with `No module named nookku` ([koodam#478](https://github.com/mohanraj00/koodam/issues/478)).

Add 2 lines to `~/.profile` to close the gaps. The second line is the fix form of koodam#478:

```bash
cat >> ~/.profile <<'EOF'
export PATH=/koodam/bin:$PATH
export PYTHONPATH=/koodam/nookku/lib PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1
EOF
```

These variables apply to each Python program of the login shell. `PYTHONSAFEPATH=1` stops Python from putting the folder of a script first on its path. `PYTHONNOUSERSITE=1` stops Python from reading the packages in `~/.local`. Thus a file in the project cannot replace a module of the pinned lib. The fix on the Nookku side is [#704](https://github.com/mohanraj00/nookku/issues/704). When a Koodam release closes the 2 issues, remove these lines.

**CAUTION:** Use Python 3.11 or later in the Workspace image. On Python 3.10, `PYTHONSAFEPATH` has no effect, so a `nookku/` folder in the project folder can replace the pinned package.

Open a new login shell, and check Nookku:

```bash
nookku --version
```

```text
nookku 0.6.0
```

In the proof, before this step, `command -v nookku` found nothing, and `python3` could not import `nookku`. After this step, `nookku` was `/koodam/bin/nookku`, with version 0.6.0. `python3` was 3.13.5, with the 2 flags on. The test folder was `/home/dev/nookku-tests`, with mode 700, on the home volume. A write to `/koodam/nookku` failed. Each plugin file in the pod had the SHA-256 of the same file at the Nookku tag `v0.6.0` ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W1).

## 5. Log in to Claude Code

Do this step only for the evaluation in step 9. The prompts of steps 6 to 8 go to the plugin, not to the model.

Do this step outside the pod. A person must make a token and store it in the namespace of the Workspace:

```bash
claude setup-token
koodam login claude-code -n dev-shop
```

Kubernetes updates a mounted Secret after a short time ([Kubernetes docs](https://kubernetes.io/docs/concepts/configuration/secret/#using-secrets-as-files-from-a-pod)). A new login shell in the pod then has `CLAUDE_CODE_OAUTH_TOKEN`. The login shell also has the env of the gateway, and Claude Code uses the gateway env first. Thus step 9 removes the gateway env before it starts `claude`.

## 6. Make the project

In the pod, make the project and copy the entry into it. The entry `service_entry.py` sends each message to the Service URL in `TOY_SHOP_URL`. It starts no server:

```bash
mkdir -p ~/toy-shop/.nookku && cd ~/toy-shop
```

Copy [examples/toy-shop/service_entry.py](../examples/toy-shop/service_entry.py) to `~/toy-shop/` with `kubectl cp`. Then write `.nookku/config.json`:

```json
{
 "entry": ["python3", "service_entry.py"],
 "agent_url": "http://toy-shop.shop.svc:8080/",
 "egress_ignore": ["api.anthropic.com", "koodam-litellm.koodam-system.svc:4000"]
}
```

The entry imports `nookku`. It gets the pinned lib from the `PYTHONPATH` of step 4. `agent_url` lets the guard deny a direct call from the model to the agent ([how-to/http-tap.md](how-to/http-tap.md#an-agent-in-a-cluster)). `egress_ignore` keeps the hosts of the harness out of the egress findings ([reference/config.md](reference/config.md#test-keys)). The proof measured the hosts of the harness with 1 blocked prompt before the test, and found 2 hosts: `api.anthropic.com` and the gateway Service `koodam-litellm.koodam-system.svc:4000` ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), `harness_hosts_ignored`).

Register the egress answer, with the toy shop Service as a backend:

```bash
nookku register <<'EOF'
{"model_apis": [],
 "backends": [{"name": "toy-shop", "env": "TOY_SHOP_URL", "url": "http://toy-shop.shop.svc:8080/"}],
 "mcp_servers": [], "databases": [], "other": []}
EOF
```

At the start, the test gives `TOY_SHOP_URL` the URL of a recording proxy. Thus `backend.jsonl` records each call of the entry to the Service.

## 7. Run the test

In the pod, start `claude` in `~/toy-shop` with the plugin folder of the preset. Koodam v0.5.0 does not load the plugin:

```bash
claude --plugin-dir /koodam/nookku/plugin
```

Type each prompt:

```text
nookku start
hi, the mug i ordered came with a crack in the handle
ok what is your refund policy
do you ship to delhi?
```

Each reply shows as the reason of the blocked prompt. Then end the test in a shell. This ends the test with no evaluation, so that you can add the egress spans first:

```bash
nookku end
```

In the proof, Claude Code loaded the plugin `nookku@inline` from `/koodam/nookku/plugin`, and the only MCP server of a plugin was `plugin:nookku:nookku`. The test folder was in `/home/dev/nookku-tests`. Each message went through the [tap](reference/glossary.md#tap) to the agent at the Service URL, and each reply reached the [relay](reference/glossary.md#relay), byte for byte. The [relay record](reference/glossary.md#relay-record), the [tap record](reference/glossary.md#tap-record) and the backend record agreed for each of the 3 turns, and the audit found 0 [breaks](reference/glossary.md#break). The model wrote 0 output tokens for each message ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W1 and W2).

## 8. Give the egress spans to the trace

The egress spans are in the logs of the proxy pods. Export them outside the pod, for the time of the test. The manifest of the test gives the start and the end (`started` and `ended`, in seconds). The values below are the times of the proof test:

```bash
koodam -n dev-shop trace workspace/shop --json \
  --since 2026-11-27T12:39:51Z --until 2026-11-27T12:40:04Z > spans.jsonl
kubectl cp spans.jsonl dev-shop/shop-0:/home/dev/spans.jsonl -c workspace
```

In the pod, give the file to the trace:

```bash
cd ~/toy-shop
nookku trace --egress ~/spans.jsonl
```

The trace copies the file into the test folder as `egress.jsonl`, adds it to the [seal](reference/glossary.md#seal), and gives the findings `egress_not_in_discovery` and `egress_denied` ([SPEC.md section 8.8](../SPEC.md#88-egress-spans)).

To show the 2 findings, the proof made 2 calls from the pod after turn 2, around the proxies of Nookku:

- An HTTP call to `example.com`. The egress answer does not name this host, so the trace gives `egress_not_in_discovery` for it.
- A `CONNECT` to `example.com` port 22 through the Koodam proxy. The proxy denied it with `403 Forbidden`, so the trace gives `egress_denied` with the detail `connect example.com port 22: denied (port)`.

In the proof, `egress.jsonl` had the bytes of the export, and the seal covered it. The trace gave 1 `egress_not_in_discovery` and 1 `egress_denied`, and no span named the Service ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W3). The calls to the Service go directly through `extraEgress`, so they have no span.

If the app gets its model key from the LiteLLM gateway of Koodam, `nookku trace --gateway SOURCE --key-alias ALIAS` reads the spend logs of that key into `gateway.jsonl` ([SPEC.md section 8.9](../SPEC.md#89-gateway-logs)). The toy shop agent of this page calls no model, so the proof does not use it. The CI job `kind-testkey` reads the logs of a test key from the bundled gateway ([The Koodam tag of the CI job](#the-koodam-tag-of-the-ci-job)).

## 9. Evaluate the test

The evaluation needs a real model, and the mock model of the bundled gateway cannot write a report. Do the login of step 5. In the pod, remove the gateway env, and start `claude` again in `~/toy-shop`:

```bash
unset ${!ANTHROPIC_@} CLAUDE_CODE_SUBAGENT_MODEL
claude --plugin-dir /koodam/nookku/plugin --add-dir /home/dev/nookku-tests
```

Type the prompt `nookku end`. The test already ended, so the plugin starts the evaluation of the ended test. The model reads the records and the findings, and writes `report.md` in the test folder.

Then check the seal:

```bash
nookku verify
```

The proof run on this page did no login, so it has no evaluation. With no `--no-evaluation`, the proof waits for the login of a person, and writes `proofs/cluster/plugin-claude-code.json` ([method](../scripts/proof_cluster.py), W4). The last run with an evaluation used Koodam 0.3.0 ([Limits](#limits)).

## 10. Clean up

```bash
kubectl delete namespace dev-shop shop
helm uninstall koodam -n koodam-system
kubectl delete namespace koodam-system
```

If you made a kind cluster for this tutorial, delete it with `kind delete cluster --name <name>`.

## The Koodam release of the proof

[scripts/proof_cluster.py](../scripts/proof_cluster.py) pins these values of the Koodam release `v0.5.0`:

| Value | Where |
|---|---|
| The git tag `v0.5.0` and its commit `a08e48c52915b01609d5e50ae660495232328432` | `KOODAM_TAG` and `KOODAM_COMMIT` |
| The chart `oci://ghcr.io/mohanraj00/charts/koodam` version `0.5.0`, digest `sha256:746593cfa80ee90bf4a4244d64aba072ce5cd1c8bc3ae720a0d2f1357e6032f2` | `CHART`, `KOODAM` and `CHART_DIGEST` |
| The Nookku data image `ghcr.io/mohanraj00/koodam-nookku@sha256:be6c674c2699532e3d2b94a89a96b3ad7ea9b92ac0e694459987e1fe2e9d2a2e` of the tag `0.5.0` | `NOOKKU_IMAGE`, the chart value `nookku.image` |
| The Workspace image `ghcr.io/mohanraj00/koodam-workspace:0.5.0@sha256:b4f428400d0bda4e8698b92bcc12111e1f25213ea6ce4c6a804c787ec566180a`, the base of the local image with `python3` | `WORKSPACE_BASE` |
| Nookku 0.6.0, the pin of the data image | `PRESET_NOOKKU`. W1 compares the plugin files with the files of the git tag `v0.6.0`. |

To change the release:

1. Use only a tag of a Koodam release.
2. Set the commit, the chart digest and the image digests of the new tag.
3. Change the values in this section and in steps 1 and 3.
4. Run `python scripts/proof_cluster.py plugin-claude-code --no-evaluation`, and commit the result in `proofs/cluster/`.

## The Koodam tag of the CI job

The tutorial on this page uses Koodam 0.3.0. The CI job `kind-testkey` uses a later tag, because a gateway key for each test came with Koodam `v0.4.0-alpha.1` ([koodam#192](https://github.com/mohanraj00/koodam/issues/192)). The job runs [scripts/kind_testkey.py](../scripts/kind_testkey.py). It installs the chart with `gateway.mode: bundled` and the mock model of the bundled gateway, so it needs no model key. It makes a TestKey for each of 2 tests, and runs each test in the Workspace with the key of the TestKey ([SPEC.md section 7.16](../SPEC.md#716-gateway-key-of-a-test)).

The job pins these values:

| Value | Where |
|---|---|
| The git tag `v0.4.0-alpha.1` | `KOODAM_TAG` in [scripts/kind_testkey.py](../scripts/kind_testkey.py) |
| The commit `74920bed1d5c4575dbe3dc60c33ba6e07b73d44c` of the tag | `KOODAM_COMMIT` in the same file |
| The chart `oci://ghcr.io/mohanraj00/charts/koodam` version `0.4.0-alpha.1` | The script removes the `v` of the tag. |
| The images `ghcr.io/mohanraj00/koodam:0.4.0-alpha.1` and `ghcr.io/mohanraj00/koodam-workspace:0.4.0-alpha.1` | The chart uses its own version as the image tag. |

To change the tag:

1. Use only a tag of a Koodam release. Do not use a branch or a commit with no tag.
2. Set `KOODAM_TAG` to the new tag, and `KOODAM_COMMIT` to its commit (`git rev-parse <tag>^{commit}` in a Koodam checkout).
3. Change the tag in this section and in [SPEC.md section 7.16](../SPEC.md#716-gateway-key-of-a-test).
4. Run `python scripts/kind_testkey.py` on a computer with Docker, kind, kubectl, helm and uv. Then open a PR. The CI job runs the script again.

The job writes its result to the artifact `kind-testkey`. The result has no key value.

## The Koodam tag of the release samples

Each Koodam release has sample files of the telemetry that the release writes. The release workflow of Koodam makes them from a kind run of the tagged commit, so no person writes them ([koodam#331](https://github.com/mohanraj00/koodam/issues/331)). The CI job `release-samples` runs [scripts/release_samples.py](../scripts/release_samples.py) on the samples of one tag. It needs no cluster and no model.

The script does these checks:

- S1: each sample file has the SHA-256 of the pin.
- S2: the span reader reads `egress-spans.jsonl` ([SPEC.md section 8.8](../SPEC.md#88-egress-spans)). The file has 1 span or more, and no line is invalid.
- S3: the gateway reader reads `gateway-log.jsonl` ([SPEC.md section 8.9](../SPEC.md#89-gateway-logs)). Each line is a log with a start time and a key alias, and 1 log or more is a model call that the reader knows.
- S4: the ingress span reader reads `app-ingress-spans.jsonl` ([SPEC.md section 8.12](../SPEC.md#812-ingress-spans)). The file has 1 span or more, and no line is invalid.

The job pins these values:

| Value | Where |
|---|---|
| The git tag `v0.4.0` | `KOODAM_TAG` in [scripts/release_samples.py](../scripts/release_samples.py) |
| The commit `1a8c3a133c4155e1120268109e7436d07cbcb095` of the tag | `KOODAM_COMMIT` in the same file |
| The SHA-256 of `egress-spans.jsonl`, of `gateway-log.jsonl` and of `app-ingress-spans.jsonl` | `SAMPLES` in the same file |

With the tag `v0.4.0`, the span sample has 7 lines: 6 spans of contract version 2 that the reader keeps, and 1 span of the kind `llm` that the reader counts and does not keep. The log sample has 1 log, and it is a model call. The ingress sample has 305 spans of version 1: 295 with the outcome `ok`, 5 with `syntax` and 5 with `signature` ([data](../proofs/release-samples/results.json)).

If a span of a new tag has a version that this Nookku does not read, its reader stops, and the job fails with the message of the reader. The message names the line and the version. Then add the version to the reader before you change the pin.

The cases that a person wrote stay as unit cases: [tests/test_egress_spans.py](../tests/test_egress_spans.py), [tests/test_gateway.py](../tests/test_gateway.py), [tests/test_ingress_spans.py](../tests/test_ingress_spans.py), [conformance/gateway/](../conformance/gateway/) and the cases `ingress_spans*` in [conformance/trace/](../conformance/trace/).

To change the tag:

1. Use only a tag of a Koodam release that has the sample files.
2. Set `KOODAM_TAG` to the new tag, and `KOODAM_COMMIT` to its commit (`git rev-parse <tag>^{commit}` in a Koodam checkout). Set each value of `SAMPLES` to the SHA-256 of the file in `checksums.txt` of the release.
3. Change the tag in this section.
4. Run `python scripts/release_samples.py`, and commit `proofs/release-samples/results.json`. Then open a PR. The CI job runs the script again.

If S1 fails for a tag that did not change, do not change the pin. A release does not change its files.

## Limits

- Koodam v0.5.0 does not put `/koodam/bin` on the PATH of a login shell ([koodam#476](https://github.com/mohanraj00/koodam/issues/476)). The launcher does not give the pinned lib to the child processes of Nookku ([koodam#478](https://github.com/mohanraj00/koodam/issues/478), [#704](https://github.com/mohanraj00/nookku/issues/704)). Step 4 closes both gaps with 2 lines in `~/.profile`.
- Koodam v0.5.0 does not load the plugin in the harness. Give `--plugin-dir /koodam/nookku/plugin` to `claude` each time.
- The default Workspace image has no Python. You build an image with `python3` 3.11 or later and give it to the cluster.
- The proof of this page ran with the mock model and no login, so it has no evaluation. The last run with an evaluation (W4) used Koodam 0.3.0 and Nookku 0.5.7 ([data](../proofs/cluster/plugin-claude-code.json)).
- This page does not cover Codex. The last Codex proof used Koodam 0.3.0. It passed W1 to W3, and Codex wrote no report ([data](../proofs/cluster/plugin-codex.json), [method of that run](https://github.com/mohanraj00/nookku/blob/3d4d6945/scripts/proof_cluster.py), [koodam#243](https://github.com/mohanraj00/koodam/issues/243)).
- The egress spans show the hosts of the connections, not each call ([limits.md](limits.md)). The calls to the Service and the calls inside the pod have no span.
- The export of the spans runs outside the pod, because the Workspace has no access to the logs of the proxy pods.
- The proof uses a kind cluster.
