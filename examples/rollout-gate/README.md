# Rollout gate

This example shows how a rollout controller uses a gate result of Nookku. It uses the Python standard library only, and it has no model. It is the example of [docs/how-to/gate-a-rollout.md](../../docs/how-to/gate-a-rollout.md).

- [agent_v1.py](agent_v1.py) is version 1 of a toy shop agent. It speaks the agent contract on stdin and stdout ([SPEC.md section 6](../../SPEC.md#6-agent-contract-version-1)), and asks a stock service for the blue mug.
- [agent_v2.py](agent_v2.py) is version 2, with a planted defect. In each turn, it also asks the stock service for a product that the service does not know. Its replies are the same as the replies of version 1.
- [gate.json](gate.json) is the gate file: 1 scripted test with the limit `backend_error: 0`.
- [script.jsonl](script.jsonl) is the script of 3 messages.
- [controller.py](controller.py) is a toy rollout controller. It reads `result.json` and the copy of the seal, and prints `promote` or `stop`.

## Run it

[scripts/proof_rollout_gate.py](../../scripts/proof_rollout_gate.py) runs the 2 versions with a toy stock service:

```bash
uv run python scripts/proof_rollout_gate.py
```

Version 1 passes the gate, and the controller promotes it. Version 2 fails the gate with 3 `backend_error` findings, and the controller stops the rollout ([data](../../proofs/rollout-gate/results.json)).
