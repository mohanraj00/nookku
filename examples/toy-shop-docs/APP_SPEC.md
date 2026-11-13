# Toy shop support

The agent answers questions about returns and shipping. Each answer comes from one section of the store in `store/`, and the reply gives the locator of that section.

## Answer key

| File | Field | Match |
|---|---|---|
| `keys/sources.json` | `source` | exact |

## Verdict

| Finding | Most |
|---|---|
| `agent_error` | 0 |
| `answer_key_mismatch` | 0 |
| `answer_key_missing` | 0 |
