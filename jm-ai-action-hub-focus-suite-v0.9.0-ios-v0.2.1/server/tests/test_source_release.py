from __future__ import annotations

import io
import sys
import tarfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script_module(module_name: str):
    if loaded := sys.modules.get(module_name):
        return loaded
    spec = spec_from_file_location(module_name, SCRIPTS / f"{module_name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load script module {module_name}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


build_source_release = load_script_module("build_source_release")
verify_source_release = load_script_module("verify_source_release")
ARCHIVE_ROOT = build_source_release.ARCHIVE_ROOT
REPOSITORY_ROOT = build_source_release.REPOSITORY_ROOT
build_archive = build_source_release.build_archive
is_forbidden_path = build_source_release.is_forbidden_path
EXPECTED_ENV_KEYS = verify_source_release.EXPECTED_ENV_KEYS
SourceReleaseVerificationError = verify_source_release.SourceReleaseVerificationError
validate_env_template = verify_source_release.validate_env_template
verify_archive = verify_source_release.verify_archive


def make_release_tree(tmp_path: Path, *, legal_files: bool) -> Path:
    tmp_path.mkdir()
    for directory in ("server", "ios", "contracts", "docs"):
        (tmp_path / directory).mkdir()
    (tmp_path / "server" / ".env.example").write_text(
        (REPOSITORY_ROOT / "server" / ".env.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "server" / "source.py").write_text("print('source')\n", encoding="utf-8")
    (tmp_path / "ios" / "source.swift").write_text("import Foundation\n", encoding="utf-8")
    (tmp_path / "contracts" / "contract.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "RELEASE_INFO.json").write_text('{"server_version":"0.9.0"}\n', encoding="utf-8")
    (tmp_path / "RELEASE_MANIFEST.sha256").write_text("manifest\n", encoding="utf-8")
    if legal_files:
        (tmp_path / "LICENSE").write_text("owner supplied license\n", encoding="utf-8")
        (tmp_path / "NOTICE").write_text("owner supplied notice\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("legal_files", [False, True])
def test_archive_layout_is_reproducible_and_legal_files_are_optional(
    tmp_path: Path, legal_files: bool
) -> None:
    repository = make_release_tree(tmp_path / "repository", legal_files=legal_files)
    first, first_sha, _ = build_archive(tmp_path / "first.tar.gz", repository)
    second, second_sha, _ = build_archive(tmp_path / "second.tar.gz", repository)

    assert first_sha == second_sha
    summary = verify_archive(second)
    assert summary.forbidden_count == 0
    with tarfile.open(first, mode="r:gz") as archive:
        names = {member.name.rstrip("/") for member in archive.getmembers()}
    assert ARCHIVE_ROOT in names
    assert f"{ARCHIVE_ROOT}/server/.env.example" in names
    assert (f"{ARCHIVE_ROOT}/LICENSE" in names) is legal_files
    assert (f"{ARCHIVE_ROOT}/NOTICE" in names) is legal_files


def test_archive_excludes_symlinks(tmp_path: Path) -> None:
    repository = make_release_tree(tmp_path / "repository", legal_files=False)
    (repository / "docs" / "linked-guide").symlink_to(repository / "docs" / "guide.md")

    archive, _, _ = build_archive(tmp_path / "source.tar.gz", repository)

    with tarfile.open(archive, mode="r:gz") as stream:
        names = {member.name.rstrip("/") for member in stream.getmembers()}
    assert f"{ARCHIVE_ROOT}/docs/linked-guide" not in names


@pytest.mark.parametrize(
    "path",
    [
        ".git/config",
        ".serena/project.yml",
        "server/.venv/bin/python",
        "ios/.build/debug",
        "server/__pycache__/settings.pyc",
        "server/.pytest_cache/v/cache",
        "server/.ruff_cache/0",
        "server/.coverage",
        "server/.coverage.worker-123",
        "server/coverage.xml",
        "server/htmlcov/index.html",
        "ios/DerivedData/build",
        "server/backups/archive.tar.gz",
        "server/dist/package.whl",
        "server/data/action_hub.db",
        "ios/build.ipa",
        "ios/App.xcarchive",
        "ios/App.dSYM",
        "server/.env",
        "ios/.env.local",
    ],
)
def test_forbidden_paths_are_rejected(path: str) -> None:
    assert is_forbidden_path(path)


@pytest.mark.parametrize(
    ("replacement", "expected_error"),
    [
        ("ACTION_HUB_UNKNOWN=value\n", "key mismatch"),
        ("", "key mismatch"),
        ("ACTION_HUB_GITHUB_TOKEN=not-allowed", "credential values"),
        ("ACTION_HUB_LLM_BASE_URL=https://user:password@example.com", "URL userinfo"),
    ],
)
def test_template_validation_rejects_invalid_values(
    replacement: str, expected_error: str
) -> None:
    template = (REPOSITORY_ROOT / "server" / ".env.example").read_text(encoding="utf-8")
    if replacement == "":
        template = "\n".join(
            line
            for line in template.splitlines()
            if not line.startswith("ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION=")
        )
    elif replacement.startswith("ACTION_HUB_UNKNOWN"):
        template = f"{template}\n{replacement}"
    else:
        key = replacement.split("=", 1)[0]
        template = "\n".join(
            replacement if line.startswith(f"{key}=") else line for line in template.splitlines()
        )

    with pytest.raises(SourceReleaseVerificationError, match=expected_error):
        validate_env_template(template)


def test_template_validation_rejects_future_nonempty_credential_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_key = "ACTION_HUB_FUTURE_SERVICE_API_KEY"
    monkeypatch.setattr(
        "verify_source_release.EXPECTED_ENV_KEYS", EXPECTED_ENV_KEYS | {future_key}
    )
    template = (REPOSITORY_ROOT / "server" / ".env.example").read_text(encoding="utf-8")

    with pytest.raises(SourceReleaseVerificationError, match="credential values"):
        validate_env_template(f"{template}\n{future_key}=must-be-rejected\n")


def test_archive_excludes_local_coverage_file_without_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = make_release_tree(tmp_path / "repository", legal_files=False)
    coverage_file = repository / "server" / ".coverage"
    coverage_file.write_text("local coverage must not be read", encoding="utf-8")
    original_open = Path.open

    def fail_if_coverage_is_opened(path: Path, *args, **kwargs):
        if path == coverage_file:
            raise AssertionError("source archive builder must not read local coverage")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_if_coverage_is_opened)
    archive, _, _ = build_archive(tmp_path / "source.tar.gz", repository)

    with tarfile.open(archive, mode="r:gz") as stream:
        names = {member.name.rstrip("/") for member in stream.getmembers()}
    assert f"{ARCHIVE_ROOT}/server/.coverage" not in names


def write_malicious_archive(
    archive_path: Path, entries: list[tuple[str, bytes, bytes | None, str | None]]
) -> Path:
    with tarfile.open(archive_path, mode="w:gz") as archive:
        root = tarfile.TarInfo(f"{ARCHIVE_ROOT}/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for name, content, member_type, linkname in entries:
            info = tarfile.TarInfo(name)
            if member_type is not None:
                info.type = member_type
            if linkname is not None:
                info.linkname = linkname
            if info.isfile():
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            else:
                archive.addfile(info)
    return archive_path


def test_archive_verification_requires_exactly_one_root_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "missing-root.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        info = tarfile.TarInfo(f"{ARCHIVE_ROOT}/server/source.py")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(SourceReleaseVerificationError, match="exactly one archive root"):
        verify_archive(archive_path)


@pytest.mark.parametrize(
    ("entries", "expected_error"),
    [
        ([(f"{ARCHIVE_ROOT}/../escape.py", b"x", None, None)], "Path traversal"),
        ([(f"/{ARCHIVE_ROOT}/server/escape.py", b"x", None, None)], "Absolute"),
        ([(f"{ARCHIVE_ROOT}/server//escape.py", b"x", None, None)], "Non-normal"),
        ([(f"{ARCHIVE_ROOT}/", b"", tarfile.DIRTYPE, None)], "Duplicate archive root"),
        ([(f"{ARCHIVE_ROOT}/server/source.py/", b"x", None, None)], "Non-normal"),
        (
            [
                (f"{ARCHIVE_ROOT}/server/source.py", b"x", None, None),
                (f"{ARCHIVE_ROOT}/server/./source.py", b"x", None, None),
            ],
            "Duplicate",
        ),
        ([(f"{ARCHIVE_ROOT}/server/link", b"", tarfile.SYMTYPE, "source.py")], "Non-regular"),
        ([(f"{ARCHIVE_ROOT}/server/hardlink", b"", tarfile.LNKTYPE, "source.py")], "Non-regular"),
        ([(f"{ARCHIVE_ROOT}/server/pipe", b"", tarfile.FIFOTYPE, None)], "Non-regular"),
        ([(f"{ARCHIVE_ROOT}/.git/config", b"x", None, None)], "Forbidden archive entries"),
        ([(f"{ARCHIVE_ROOT}/server/.coverage", b"x", None, None)], "Forbidden archive entries"),
        ([(f"{ARCHIVE_ROOT}/server/.coverage.worker-123", b"x", None, None)], "Forbidden archive entries"),
        ([(f"{ARCHIVE_ROOT}/server/coverage.xml", b"x", None, None)], "Forbidden archive entries"),
        ([(f"{ARCHIVE_ROOT}/server/htmlcov/index.html", b"x", None, None)], "Forbidden archive entries"),
    ],
)
def test_archive_verification_rejects_unsafe_members_before_extraction(
    tmp_path: Path,
    entries: list[tuple[str, bytes, bytes | None, str | None]],
    expected_error: str,
) -> None:
    archive = write_malicious_archive(tmp_path / "malicious.tar.gz", entries)

    with pytest.raises(SourceReleaseVerificationError, match=expected_error):
        verify_archive(archive)
