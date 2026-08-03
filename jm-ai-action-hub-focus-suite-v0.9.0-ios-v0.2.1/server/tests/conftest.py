from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from action_hub.config import Settings
from action_hub.main import create_app

TEST_API_KEY = "test-api-key-" + ("x" * 32)
TEST_MOBILE_SECRET = "test-mobile-token-secret-" + ("y" * 32)


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        mobile_access_token_secret=TEST_MOBILE_SECRET,
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
        value.headers["X-Action-Hub-Key"] = settings.api_key
        yield value
