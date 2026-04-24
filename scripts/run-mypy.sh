#!/usr/bin/env bash
# Run `mypy --strict brain` only when brain/ has .py files.
# Phase 0 bootstrap: brain/ is empty (AGENTS.md only), and mypy fails hard on
# an empty directory. Once Phase 1 adds Python sources, mypy runs normally.

set -euo pipefail

if find brain -name '*.py' -print -quit 2>/dev/null | grep -q .; then
  exec uv run mypy --strict brain
else
  echo "skipping mypy: no .py files in brain/"
fi
