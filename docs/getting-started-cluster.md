# Get started in a cluster

In this tutorial, you test the toy shop agent in a Kubernetes cluster. The agent runs behind a Service. Claude Code runs in a [Koodam](https://github.com/mohanraj00/koodam) Workspace with traced egress. You install Nookku and the [plugin](reference/glossary.md#plugin) in the Workspace, run a test with 3 messages, give the egress spans of the test to the [trace](reference/glossary.md#trace), and start the [evaluation](reference/glossary.md#evaluation).

The values on this page come from one run of [scripts/proof_cluster.py](../scripts/proof_cluster.py) on 2026-10-30, on macOS, in a kind cluster, with Koodam 0.3.0, nookku 0.5.6 from this checkout and Claude Code 2.1.302 ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), [records](../proofs/cluster/plugin-claude-code-no-evaluation/)). That run did steps 1 to 8 and no login, so it has no evaluation. The script does each step of this page with `kubectl exec`, and gives each prompt to `claude -p` in the pod. The test id and the times are different on your cluster.

If you do not know Nookku, do [Get started](getting-started.md) first. It explains the [audit](reference/glossary.md#audit), the [findings](reference/glossary.md#findings) and the report.

## What you need

- A Kubernetes cluster. The proof used kind ([versions](../proofs/cluster/plugin-claude-code-no-evaluation.json)).
- `kubectl`, `helm` and the `koodam` CLI 0.3.0 ([release](https://github.com/mohanraj00/koodam/releases/tag/v0.3.0)).
- A Claude subscription for `claude setup-token`. Only the evaluation in step 9 needs it.
- A clone of this repo, for the toy shop agent and its [entry](reference/glossary.md#entry):

  ```bash
  git clone https://github.com/mohanraj00/nookku.git
  cd nookku
  ```

If you use kind on Docker Desktop, keep 1.2 GB free on the disk of Docker after the install. A full disk stops each container of Docker, also the containers of other projects. The proof stops if the node has less than 1200 MB free ([method](../scripts/proof_cluster.py)).

## 1. Install Koodam with the egress proxy

Koodam 0.3.0 has no Nookku preset ([koodam#83](https://github.com/mohanraj00/koodam/issues/83)). This page installs Nookku in the Workspace by hand (step 4).

Find the address and the port of the API server. The NetworkPolicy of the proxy needs them:

```bash
kubectl get endpointslices -n default -l kubernetes.io/service-name=kubernetes \
  -o jsonpath='{.items[0].endpoints[0].addresses[0]} {.items[0].ports[0].port}'
```

Write `values.yaml`. Put the address and the port of the API server in `apiServer`. The `extraEgress` rule lets the Workspace pods call the toy shop Service directly, with no proxy:

```yaml
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

Install the chart:

```bash
kubectl create namespace koodam-system
kubectl create namespace shop
kubectl create namespace dev-shop
kubectl -n koodam-system create secret generic koodam-gateway \
  --from-literal=master-key="sk-$(openssl rand -hex 32)"
helm install koodam oci://ghcr.io/mohanraj00/charts/koodam --version 0.3.0 \
  -n koodam-system -f values.yaml --wait --timeout 10m \
  --set gateway.mode=existing --set gateway.url=http://gateway.invalid:4000
```

The Workspace of this page uses the subscription login of Claude Code, so it calls no gateway. The chart 0.3.0 needs a gateway mode and a URL. Thus this page gives the mode `existing` and a URL that nothing uses.

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

## 3. Make the Workspace

The Workspace keeps the [test folders](reference/glossary.md#test-folder) on a separate volume at `/tests`, so that you can read them from another pod:

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
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shop-nookku-tests
  namespace: dev-shop
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: core.koodam.dev/v1alpha1
kind: Workspace
metadata:
  name: shop
  namespace: dev-shop
spec:
  storage: 5Gi
  harnesses:
    - name: claude-code
      version: 2.1.302
  podTemplate:
    spec:
      containers:
        - name: workspace
          volumeMounts:
            - name: nookku-tests
              mountPath: /tests
      volumes:
        - name: nookku-tests
          persistentVolumeClaim:
            claimName: shop-nookku-tests
EOF
kubectl -n dev-shop wait workspace/shop --for=jsonpath='{.status.phase}'=Running --timeout=600s
kubectl -n dev-shop get workspace shop -o jsonpath='{.status.conditions[?(@.type=="TracedEgress")].status}'
```

```text
True
```

In the proof, the Workspace was `Running` and `TracedEgress` was `True` ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W1).

## 4. Install Nookku and the plugin in the Workspace

Open a login shell in the Workspace pod. Do the next commands of this step in that shell:

```bash
kubectl -n dev-shop exec -it shop-0 -c workspace -- bash -l
```

The Workspace image has no Python and no curl. Get the `uv` binary for Linux outside the pod, from its [release](https://github.com/astral-sh/uv/releases), and copy it to `~/.local/bin/uv` in the pod with `kubectl cp`. The proof used uv 0.10.8, and checked its sha256. Then install Nookku. `uv` gets Python through the egress proxy:

```bash
uv tool install nookku
nookku --version
```

Add the marketplace and install the plugin:

```bash
claude plugin marketplace add mohanraj00/nookku
claude plugin install nookku@nookku
```

The proof installed the wheel and the plugin of this checkout from local copies. In the proof, Claude Code in the pod loaded the plugin `nookku@nookku`, and the only MCP server was `plugin:nookku:nookku` ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W1).

Put the tests folder on the volume of step 3:

```bash
echo 'export NOOKKU_TESTS_DIR=/tests' >> ~/.profile
```

## 5. Log in to Claude Code

Do this step outside the pod. A person must do it. Make a token, and store it in the namespace of the Workspace:

```bash
claude setup-token
koodam login claude-code -n dev-shop
```

Kubernetes updates a mounted Secret after a short time ([Kubernetes docs](https://kubernetes.io/docs/concepts/configuration/secret/#using-secrets-as-files-from-a-pod)). A new login shell in the pod then has `CLAUDE_CODE_OAUTH_TOKEN`. The prompts of steps 6 to 8 go to the plugin, not to the model. Only the evaluation in step 9 needs the login.

## 6. Make the project

In the pod, make the project and copy the entry into it. The entry `service_entry.py` sends each message to the Service URL in `TOY_SHOP_URL`. It starts no server:

```bash
mkdir -p ~/toy-shop/.nookku && cd ~/toy-shop
```

Copy [examples/toy-shop/service_entry.py](../examples/toy-shop/service_entry.py) to `~/toy-shop/` with `kubectl cp`. Then write `.nookku/config.json`:

```json
{
 "entry": ["uv", "run", "--with", "nookku", "python3", "service_entry.py"],
 "agent_url": "http://toy-shop.shop.svc:8080/",
 "egress_ignore": ["api.anthropic.com"]
}
```

`agent_url` lets the guard deny a direct call from the model to the agent ([how-to/http-tap.md](how-to/http-tap.md#an-agent-in-a-cluster)). `egress_ignore` keeps the hosts of the [harness](reference/glossary.md#harness) out of the egress findings ([reference/config.md](reference/config.md#test-keys)). Each start of `claude` calls `api.anthropic.com`, also for a prompt that the plugin blocks. The proof measured the hosts of the harness with 1 blocked prompt before the test, and found only `api.anthropic.com` ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), `harness_hosts_ignored`).

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

In the pod, start `claude` in `~/toy-shop`, and type each prompt:

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

In the proof, each message reached the agent at the Service, and each reply reached the [relay](reference/glossary.md#relay), byte for byte. The [relay record](reference/glossary.md#relay-record), the [tap record](reference/glossary.md#tap-record) and the backend record agreed for each of the 3 turns, and the audit found 0 [breaks](reference/glossary.md#break). The model wrote 0 output tokens for each message ([data](../proofs/cluster/plugin-claude-code-no-evaluation.json), W2).

## 8. Give the egress spans to the trace

The egress spans are in the logs of the proxy pods. Export them outside the pod, for the time of the test. The manifest of the test gives the start and the end (`started` and `ended`, in seconds). The values below are the times of the proof test:

```bash
koodam -n dev-shop trace workspace/shop --json \
  --since 2026-10-30T18:15:06Z --until 2026-10-30T18:15:12Z > spans.jsonl
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

## 9. Evaluate the test

In `claude` in the pod, type the prompt `nookku end`. The test already ended, so the plugin starts the evaluation of the ended test. The model reads the records and the findings, and writes `report.md` in the test folder. The model needs the login of step 5.

Then check the seal:

```bash
nookku verify
```

The proof run on this page did no login, so it has no evaluation. The run with the login writes `proofs/cluster/plugin-claude-code.json` ([method](../scripts/proof_cluster.py), W4).

## 10. Clean up

```bash
kubectl delete namespace dev-shop shop
helm uninstall koodam -n koodam-system
kubectl delete namespace koodam-system
```

If you made a kind cluster for this tutorial, delete it with `kind delete cluster --name <name>`.

## Limits

- Koodam 0.3.0 has no Nookku preset, so you install Nookku and the plugin by hand in each Workspace ([koodam#83](https://github.com/mohanraj00/koodam/issues/83)).
- The egress spans show the hosts of the connections, not each call ([limits.md](limits.md)). The calls to the Service and the calls inside the pod have no span.
- The export of the spans runs outside the pod, because the Workspace has no access to the logs of the proxy pods.
- The proof ran on kind only. The proof for Codex in a Workspace is not done yet.
