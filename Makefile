.PHONY: install test test-slow lint check fmt help

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

help:
	@echo "Targets: install test test-slow lint check fmt"

install:
	$(PIP) install -e ".[dev,server,diagnose,fast]"
	@test -f .env || cp .env.example .env

test:
	$(PYTHON) -m pytest tests/ -q

test-slow:
	$(PYTHON) -m pytest tests/ -m slow -q

lint:
	.venv/bin/ruff check autopsy tests examples

fmt:
	.venv/bin/ruff check autopsy tests examples --fix

check: lint test
