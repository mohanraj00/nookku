Fixes #

## What changed

<!-- Short sentences. One change for each pull request. -->

## Checks

I ran these commands, and each one exited with 0:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest && uv run python scripts/stealth.py check
claude plugin validate plugins/nookku && claude plugin test plugins/nookku
```

- [ ] CI is green.
- [ ] If this changes a relay (the plugin or the hook kit), I ran the proofs again ([docs/how-to/run-the-proofs.md](https://github.com/mohanraj00/nookku/blob/main/docs/how-to/run-the-proofs.md)). I committed the results with the harness versions that they record.

## Code quality

From [docs/code-quality.md](https://github.com/mohanraj00/nookku/blob/main/docs/code-quality.md). Mark each item that applies, and say why an item does not apply.

- [ ] **Fail closed.** If a relay path or a deny path fails, it blocks the message or the tool call.
- [ ] **Exact bytes.** No relay or proxy changes a byte of a message, a reply or a forwarded body.
- [ ] **One rule, two languages.** If Python and the plugin read the same input, one shared table of cases tests both.
- [ ] **Records.** A change to the record format or to the audit has a SPEC.md change. It also has a conformance case that I wrote by hand.
- [ ] **No secrets.** No secret header value, query value or key goes into a record.
- [ ] **Timeouts.** Each wait ends before the wait of the step around it.
- [ ] **Errors.** Each catch names its exceptions, or a comment gives the reason for a broad catch. Each error message names the cause and the next step.
- [ ] **Tests.** A bug fix has a test that fails before the fix. No test calls a real API or a real model.
- [ ] **Dependencies.** No new runtime dependency, and no GPL or AGPL dependency.
- [ ] **Docs and claims.** The text is in ASD-STE100. Each number in a doc links to its data and its method. No banned term in a file, a path or a commit message.
