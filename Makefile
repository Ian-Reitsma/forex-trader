.PHONY: install test coverage demo doctor api

install:
	uv sync --extra dev

test:
	PYTHONPATH=src pytest

coverage:
	PYTHONPATH=src pytest --cov=forex_trader --cov-report=term-missing

demo:
	PYTHONPATH=src python -m forex_trader demo --execute

doctor:
	PYTHONPATH=src python -m forex_trader doctor

api:
	PYTHONPATH=src python -m forex_trader serve
