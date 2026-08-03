#!/usr/bin/env python3
"""Build a deterministic, source-only JM-AI Action Hub release archive."""
from __future__ import annotations

import gzip
import hashlib
import os
import re
import stat
import tarfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_ROOT = "jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1"
ARCHIVE_FILENAME = f"{ARCHIVE_ROOT}-source.tar.gz"
ALLOWED_DIRECTORIES = frozenset({"server", "ios", "contracts", "docs"})
ALLOWED_ROOT_FILES = frozenset({"RELEASE_INFO.json", "RELEASE_MANIFEST.sha256"})
OPTIONAL_LEGAL_FILES = frozenset({"LICENSE", "NOTICE"})

# This is the single canonical matcher used by release construction and verification.
FORBIDDEN_PATH_PATTERN = re.compile(
    r"(^|/)(\.git|\.serena|\.venv|\.build|__pycache__|\.pytest_cache|\.ruff_cache|"
    r"DerivedData|backups|dist|htmlcov)(/|$)|(^|/)(?:\.coverage(?:\.[^/]*)?|coverage\.xml)$|"
    r"(^|/)data/.*\.db$|\.(ipa|xcarchive|dSYM)$"
)


class SourceReleaseError(RuntimeError):
    """A source path cannot be represented in the release archive."""


def is_allowed_env_path(relative_path: str) -> bool:
    basename = Path(relative_path).name
    if not basename.startswith(".env"):
        return True
    return relative_path == "server/.env.example"


def is_forbidden_path(relative_path: str) -> bool:
    return bool(FORBIDDEN_PATH_PATTERN.search(relative_path)) or not is_allowed_env_path(relative_path)


def is_allowed_source_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in ALLOWED_ROOT_FILES or parts[0] in OPTIONAL_LEGAL_FILES
    return parts[0] in ALLOWED_DIRECTORIES


def iter_source_files(repository_root: Path = REPOSITORY_ROOT) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for name in sorted(ALLOWED_DIRECTORIES):
        source = repository_root / name
        if not source.exists():
            continue
        if source.is_symlink():
            continue
        for current_root, directories, filenames in os.walk(source, followlinks=False):
            current = Path(current_root)
            directories[:] = sorted(
                directory
                for directory in directories
                if not (current / directory).is_symlink()
                and not is_forbidden_path((current / directory).relative_to(repository_root).as_posix())
            )
            for filename in sorted(filenames):
                candidate = current / filename
                relative = candidate.relative_to(repository_root).as_posix()
                if candidate.is_symlink() or is_forbidden_path(relative):
                    continue
                if not candidate.is_file() or not is_allowed_source_path(relative):
                    continue
                files.append((relative, candidate))

    for name in sorted(ALLOWED_ROOT_FILES | OPTIONAL_LEGAL_FILES):
        candidate = repository_root / name
        if not candidate.exists() or candidate.is_symlink():
            continue
        if not candidate.is_file():
            raise SourceReleaseError(f"Allowed root entry is not a regular file: {name}")
        files.append((name, candidate))

    return sorted(files, key=lambda entry: entry[0])


def normalized_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o755 if info.mode & stat.S_IXUSR else 0o644
    info.pax_headers = {}
    return info


def archive_output_path(repository_root: Path = REPOSITORY_ROOT) -> Path:
    configured = os.environ.get("SOURCE_RELEASE_OUTPUT")
    if configured:
        return Path(configured).expanduser().resolve()
    return repository_root / "dist" / ARCHIVE_FILENAME


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_archive(output: Path | None = None, repository_root: Path = REPOSITORY_ROOT) -> tuple[Path, str, int]:
    output = (output or archive_output_path(repository_root)).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_files = iter_source_files(repository_root)
    root_info = tarfile.TarInfo(f"{ARCHIVE_ROOT}/")
    root_info.type = tarfile.DIRTYPE
    root_info.mode = 0o755
    normalized_tar_info(root_info)

    with output.open("wb") as raw_stream:
        with gzip.GzipFile(fileobj=raw_stream, mode="wb", filename="", mtime=0) as gzip_stream:
            with tarfile.open(fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
                archive.addfile(root_info)
                for relative, source in source_files:
                    info = archive.gettarinfo(str(source), arcname=f"{ARCHIVE_ROOT}/{relative}")
                    with source.open("rb") as source_stream:
                        archive.addfile(normalized_tar_info(info), source_stream)

    digest = sha256(output)
    output.with_name(f"{output.name}.sha256").write_text(
        f"{digest}  {output.name}\n", encoding="utf-8"
    )
    return output, digest, len(source_files)


def main() -> int:
    output, digest, file_count = build_archive()
    print(f"SOURCE_RELEASE_CREATED path={output} files={file_count} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
