.PHONY: check lint types test

# Everything CI runs, in the order CI runs it. One command, no bash to copy.
check: lint types test

lint:
	.venv/bin/ruff check src tests

types:
	.venv/bin/mypy src/garmin_golf_analytics

test:
	PYTHON=.venv/bin/python ./run_tests.sh
