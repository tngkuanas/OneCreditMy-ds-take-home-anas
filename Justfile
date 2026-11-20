set shell := ["bash", "-euo", "pipefail", "-c"]

default: setup

# Install the dependencies on your machine (add your own with `uv add`).
setup:
    uv sync --locked

# Start the viewer at http://localhost:${APP_PORT:-8000}, and wait until it's up.
up:
    docker compose up -d --wait
    @echo "Viewer: http://localhost:${APP_PORT:-8000}"

# Stop the viewer.
down:
    docker compose down -v

# Check all Python code with Ruff, and the viewer with strict Pyrefly.
lint:
    uv run ruff check
    uv run ruff format --check
    uv run pyrefly check

# Run the viewer directly, without Docker.
serve:
    uv run uvicorn app.main:app --host 127.0.0.1 --port ${APP_PORT:-8000} --reload

# Generate the final summaries; Ollama must be running with qwen3.5:9b installed.
generate:
    uv run python -m company_summaries.pipeline

# Regenerate the deterministic comparison without calling a model.
baseline:
    uv run python -m company_summaries.pipeline --offline

# Re-score saved summaries; no model calls.
evaluate:
    uv run python -m company_summaries.evaluate --version v1
    uv run python -m company_summaries.evaluate --version v2
    uv run python -m company_summaries.evaluate --version rules-only --require-complete
    uv run python -m company_summaries.evaluate --version v3 --require-complete
    uv run python -m company_summaries.evaluate --version v4-rules --require-complete
    uv run python -m company_summaries.evaluate --version v4 --require-complete
    uv run python -m company_summaries.experiments
    uv run python -m company_summaries.report

test:
    uv run python -m unittest discover -s tests -v

# Full submission checks, entirely offline after dependency installation.
check: lint test evaluate
