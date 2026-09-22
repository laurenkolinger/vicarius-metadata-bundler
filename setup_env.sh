#!/usr/bin/env bash
# ============================================================================
# metadata_bundler — environment setup
# ============================================================================
# The bundler is deliberately light on dependencies. Core functionality uses
# Python 3.10+ stdlib plus PyYAML. `pandas` is optional and only consulted
# when the caller passes --csv-inspect; statistics gracefully fall back to
# stdlib csv + statistics if pandas is not available.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$HERE/.venv}"

python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install "pyyaml>=6.0"
# Optional, only used when --csv-inspect is passed:
python -m pip install "pandas>=2.0" || true

echo "metadata_bundler venv ready at: $VENV_DIR"
