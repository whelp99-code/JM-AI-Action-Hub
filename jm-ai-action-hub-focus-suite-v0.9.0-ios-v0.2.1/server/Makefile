.PHONY: install dev test coverage lint run worker worker-once migrate check verify upgrade docker-up docker-down backup

install:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e '.[dev]'

run:
	.venv/bin/action-hub serve

worker:
	.venv/bin/action-hub-worker

worker-once:
	.venv/bin/action-hub worker-once --reconcile

migrate:
	.venv/bin/action-hub migrate

check:
	.venv/bin/action-hub check

upgrade:
	./scripts/upgrade.sh

dev:
	.venv/bin/uvicorn action_hub.main:app --reload --host 0.0.0.0 --port 8787

test:
	PYTHONPATH=. .venv/bin/python -m pytest

coverage:
	PYTHONPATH=. .venv/bin/python -m pytest --cov=action_hub --cov-fail-under=80 --cov-report=term-missing

lint:
	.venv/bin/ruff check .

verify: lint coverage
	.venv/bin/python -m compileall -q action_hub tests scripts
	.venv/bin/python scripts/export_openapi.py --check
	node --check action_hub/web/app.js
	node --check action_hub/web/share-target.js

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

backup:
	./scripts/backup.sh
