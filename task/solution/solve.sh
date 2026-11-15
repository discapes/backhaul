#!/bin/bash
# Reference run: a scripted planner that plays the season through the same MCP tools as the agent.
set -euo pipefail
curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh >/dev/null
source "$HOME/.local/bin/env"
uv run --quiet --python 3.12 --with mcp==2.3.0 --with scipy==1.18.1 --with numpy==2.5.4 \
  python "$(dirname "$0")/reference.py" "${REFERENCE_WEEKS:-10}"
