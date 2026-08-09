from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from action_hub.config import Settings
from action_hub.main import create_app

TEST_API_KEY = "test-api-key-" + ("x" * 32)
TEST_MOBILE_SECRET = "test-mobile-token-secret-" + ("y" * 32)


@pytest.fixture(autouse=True, scope="session")
def _isolate_from_dotenv():
    # Settings reads .env, and tests only pin the fields they name, so every other
    # field fell back to whatever the developer had configured locally. A populated
    # .env failed five tests on facts about the machine rather than the code
    # (llm_base_url set, mobile_public_base_url set). CI never caught it because CI
    # has no .env. Thirty-eight call sites build Settings directly, so cut the
    # source off once here instead of pinning each one.
    Settings.model_config["env_file"] = None
    yield


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
