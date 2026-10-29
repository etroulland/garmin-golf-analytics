#!/bin/sh
# Tests + coverage gate. Needs: pip install -e '.[dev]'
set -e
PYTHON=${PYTHON:-python3}
"$PYTHON" -m pytest --cov --cov-report=term-missing
