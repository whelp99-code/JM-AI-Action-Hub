from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from action_hub.config import Settings
from action_hub.main import create_app


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        app_env="test",
        api_key=None,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        parser_mode="rules",
        timezone="Asia/Seoul",
        github_default_repo="whelp99-code/Proof-Graph",
    )


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value
