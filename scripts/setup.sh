#!/usr/bin/env bash
# One-time setup: Python env, install, checks, GitHub repo.
# Usage (from the repo root):  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Python 3.12 environment"
command -v python3.12 >/dev/null || brew install python@3.12
[ -d .venv ] || python3.12 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]"

echo "==> Node (for the dashboard)"
command -v node >/dev/null || brew install node

echo "==> Checks"
ruff check .
ruff format --check .
pytest -q
intenttrace version

echo "==> Git and GitHub"
if [ ! -d .git ]; then
  git init -b main
  git add .
  git commit -m "Spec, steering, and scaffold for IntentTrace"
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create intenttrace --public --source=. --push
fi

echo
echo "Setup complete. Next: open this folder in Kiro and start tasks.md, task 1."
echo "In every new terminal:  source .venv/bin/activate"
