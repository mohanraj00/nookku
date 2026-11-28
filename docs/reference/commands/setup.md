# `nookku setup`

Release: nookku 0.7.0.

Print the guide that connects a test to the app ([setup.md](../../../src/nookku/setup.md)). A [harness model](../glossary.md#harness-model) reads it. The model gives a summary of the app, asks the [tester](../glossary.md#tester) about the gaps and shows its plan. After the tester says yes, it writes the [entry](../glossary.md#entry), the config and a draft of the [app spec](../app-spec.md) ([how-to/test-your-app.md](../../how-to/test-your-app.md#2-run-the-setup-in-the-harness), [how-to/connect-your-agent.md](../../how-to/connect-your-agent.md)).

| Exit code | Meaning |
|---|---|
| 0 | Always. |

## Example

The command prints the setup guide for the harness model. These are its first lines:

```bash
nookku setup
```

```text
# Nookku setup: connect a test to this app

You configure a Nookku test for the app in this project. In a test, the tester types each message, and Nookku sends it to the app byte for byte. You do not take part in the test. You only write the connection now.

Do these 6 steps in this order: understand, interview, confirm, build, check and hand over. Steps 1 to 3 only read. Do not write, change or remove a file before the tester says yes to the plan of step 3. Do not change the app's code at any step.
...
```
