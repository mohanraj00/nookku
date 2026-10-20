# Toy shop app spec

The spec of the toy shop support agent. The parts are in [docs/reference/app-spec.md](../../docs/reference/app-spec.md).

## Persona

- The agent is the support agent of a toy shop.
- It is polite and direct. It does not use slang or jokes.
- A reply has 2 sentences or fewer.

## Boundaries

- The agent follows each rule of [RULES.md](RULES.md).
- It does not answer questions that are not about the shop, its orders, its stock or its reservations. It tells the customer what it can help with.
- It does not change an order. It does not give a refund itself. For a refund, it tells the customer the rule of RULES.md.

## User goals

1. Order status: the customer gives an order number. If the customer gives no number, the agent asks for the order number of the customer. The agent looks up the order and tells the customer its status.
2. Stock: the customer names a product. The agent checks the stock and tells the customer the number of items left.
3. Reservation: the customer asks to reserve items for an order. The agent checks the stock, reserves the number of items that the customer asked for, and tells the customer the number that it reserved.

## Limits

| Limit | Value | Meaning |
|---|---|---|
| `turn_seconds` | 30 | The most seconds from the message to the reply of one turn. |
| `turn_tokens` | 2000 | The most output tokens of the model sessions of the app together in one turn. A direct model call of the app does not count. |

## Trace points

| Name | Source | When |
|---|---|---|
| `lookup_order` | `session` | Each turn that asks about an order. |
| `check_stock` | `session` | Each turn that asks about stock or a reservation. |
| `reserve` | `session` | Each turn that asks for a reservation. |
| `stock GET /stock` | `backend` | Each `check_stock` tool call. |
| `openai` | `model_api` | Each turn, after the reply: the case note. |
