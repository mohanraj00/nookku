.PHONY: check

# Run the local checks of AGENTS.md. Make stops at the first command that fails.
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest
	uv run python scripts/stealth.py check
	claude plugin validate plugins/nookku
	claude plugin test plugins/nookku
