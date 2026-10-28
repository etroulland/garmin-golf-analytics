#!/bin/sh
# Tests + coverage gate. Needs: pip install -r requirements-dev.txt
set -e
PYTHON=${PYTHON:-python3}
"$PYTHON" -m pytest tests \
  --cov=club_report --cov=garmin_golf_fetch --cov=round_report --cov=rounds_common --cov=hole_sync --cov=scoring \
  --cov-report=term-missing --cov-fail-under=90
