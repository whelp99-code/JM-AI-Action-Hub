ACTION_HUB_HOST ?= 127.0.0.1

.PHONY: install dev test coverage lint run worker worker-once migrate check verify docs-check source-release verify-source-release rehearse-backup-restore acceptance-security acceptance-smoke acceptance-local upgrade docker-up docker-down backup

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
	.venv/bin/uvicorn action_hub.main:app --reload --host $(ACTION_HUB_HOST) --port 8787

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

docs-check:
	.venv/bin/python scripts/validate_current_docs.py
	bash -n scripts/backup.sh scripts/restore.sh scripts/smoke_test.sh

source-release:
	.venv/bin/python scripts/build_source_release.py

verify-source-release:
	.venv/bin/python scripts/verify_source_release.py

rehearse-backup-restore:
	./scripts/rehearse_backup_restore.sh

acceptance-security:
	./scripts/acceptance_local.sh --security

acceptance-smoke:
	./scripts/acceptance_local.sh --smoke

acceptance-local:
	./scripts/acceptance_local.sh --local

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

backup:
	./scripts/backup.sh
