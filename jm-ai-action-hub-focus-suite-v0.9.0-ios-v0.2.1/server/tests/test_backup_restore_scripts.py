from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
BACKUP = SERVER_ROOT / "scripts" / "backup.sh"
RESTORE = SERVER_ROOT / "scripts" / "restore.sh"
ACTION_HUB = SERVER_ROOT / ".venv" / "bin" / "action-hub"


def file_manifest(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def write_archive(path: Path, entries: list[tuple[str, bytes, bytes | None, str | None]]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
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
    return path


def test_backup_is_data_only_and_excludes_env_files(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    (source / "action_hub.db").write_text("sqlite fixture", encoding="utf-8")
    (source / ".env").write_text("must-not-archive", encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"

    result = subprocess.run(
        [str(BACKUP), "--source-data", str(source), "--output", str(archive)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    with tarfile.open(archive, "r:gz") as stream:
        names = stream.getnames()
    assert "data/action_hub.db" in names
    assert not any(Path(name).name.startswith(".env") for name in names)


def test_legacy_backup_uses_a_new_collision_safe_archive_name(tmp_path: Path) -> None:
    isolated_server = tmp_path / "server"
    script_dir = isolated_server / "scripts"
    script_dir.mkdir(parents=True)
    isolated_backup = script_dir / "backup.sh"
    shutil.copy2(BACKUP, isolated_backup)
    data = isolated_server / "data"
    data.mkdir()
    (data / "action_hub.db").write_text("sqlite fixture", encoding="utf-8")

    first = subprocess.run([str(isolated_backup)], text=True, capture_output=True, check=False)
    second = subprocess.run([str(isolated_backup)], text=True, capture_output=True, check=False)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    first_archive = Path(first.stdout.strip())
    second_archive = Path(second.stdout.strip())
    assert first_archive.parent == isolated_server / "backups"
    assert second_archive.parent == isolated_server / "backups"
    assert first_archive != second_archive
    assert first_archive.is_file()
    assert second_archive.is_file()


@pytest.mark.parametrize(
    ("source_data", "output_name"),
    [
        ("/", "backup.tar.gz"),
        ("source/..", "backup.tar.gz"),
        ("source", "output/.."),
    ],
)
def test_backup_rejects_root_and_non_normal_explicit_paths(
    tmp_path: Path, source_data: str, output_name: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    resolved_source = source_data.replace("source", str(source), 1)
    resolved_output = output_name.replace("output", str(output_parent), 1)

    result = subprocess.run(
        [str(BACKUP), "--source-data", resolved_source, "--output", resolved_output],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert not (tmp_path / "backup.tar.gz").exists()


@pytest.mark.parametrize("output_kind", ["regular", "symlink", "hardlink"])
def test_backup_rejects_every_preexisting_output_without_mutating_protected_inode(
    tmp_path: Path, output_kind: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    protected = tmp_path / "protected.tar.gz"
    protected.write_text("unchanged protected inode", encoding="utf-8")
    protected_before = protected.read_bytes()
    output = tmp_path / "output.tar.gz"
    if output_kind == "regular":
        output = protected
    elif output_kind == "symlink":
        output.symlink_to(protected)
    else:
        os.link(protected, output)

    result = subprocess.run(
        [str(BACKUP), "--source-data", str(source), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert protected.read_bytes() == protected_before


def test_backup_rejects_caller_controlled_symlink_source_ancestor_before_reading(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-source-parent"
    real_parent.mkdir()
    source = real_parent / "source"
    source.mkdir()
    (source / "keep.txt").write_text("unchanged", encoding="utf-8")
    source_alias = tmp_path / "source-alias"
    source_alias.symlink_to(real_parent, target_is_directory=True)
    output = tmp_path / "backup.tar.gz"

    result = subprocess.run(
        [str(BACKUP), "--source-data", str(source_alias / "source"), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert not output.exists()
    assert (source / "keep.txt").read_text(encoding="utf-8") == "unchanged"


def test_backup_rejects_caller_controlled_symlink_output_ancestor_before_writing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_text("unchanged", encoding="utf-8")
    real_parent = tmp_path / "real-output-parent"
    real_parent.mkdir()
    protected = real_parent / "backup.tar.gz"
    protected.write_text("unchanged protected target", encoding="utf-8")
    protected_before = protected.read_bytes()
    output_alias = tmp_path / "output-alias"
    output_alias.symlink_to(real_parent, target_is_directory=True)

    result = subprocess.run(
        [str(BACKUP), "--source-data", str(source), "--output", str(output_alias / "backup.tar.gz")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert protected.read_bytes() == protected_before


def test_restore_accepts_safe_tar_archive_and_replaces_target_after_check(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    database = source / "action_hub.db"
    environment = {
        **os.environ,
        "ACTION_HUB_APP_ENV": "development",
        "ACTION_HUB_MOBILE_ENABLED": "false",
        "ACTION_HUB_DATABASE_URL": f"sqlite+pysqlite:///{database}",
        "ACTION_HUB_DATA_DIR": str(source),
    }
    migrated = subprocess.run(
        [str(ACTION_HUB), "migrate"], text=True, capture_output=True, check=False, env=environment
    )
    assert migrated.returncode == 0, migrated.stderr
    (source / "marker.txt").write_text("restored", encoding="utf-8")
    archive = tmp_path / "safe.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(source, arcname="data")

    target = tmp_path / "target"
    target.mkdir()
    (target / "marker.txt").write_text("mutated", encoding="utf-8")
    result = subprocess.run(
        [str(RESTORE), "--archive", str(archive), "--target-data", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "RESTORE_OK" in result.stdout
    assert (target / "marker.txt").read_text(encoding="utf-8") == "restored"


@pytest.mark.parametrize(
    ("entry", "member_type"),
    [
        ("/data/escape", None),
        ("data/../escape", None),
        ("data/link", tarfile.SYMTYPE),
        ("data/hard", tarfile.LNKTYPE),
    ],
)
def test_restore_rejects_malicious_archives_without_mutating_target(
    tmp_path: Path, entry: str, member_type: bytes | None
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    before = file_manifest(target)
    archive = write_archive(
        tmp_path / "malicious.tar.gz",
        [("data", b"", tarfile.DIRTYPE, None), (entry, b"bad", member_type, "target" if member_type else None)],
    )

    result = subprocess.run(
        [str(RESTORE), "--archive", str(archive), "--target-data", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64, result.stderr
    assert file_manifest(target) == before


def test_restore_rejects_unsafe_target_arguments_without_mutating_target(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "safe.tar.gz", [("data", b"", tarfile.DIRTYPE, None)])
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    before = file_manifest(target)
    target_symlink = tmp_path / "target-link"
    target_symlink.symlink_to(target, target_is_directory=True)
    existing_file = tmp_path / "existing-file"
    existing_file.write_text("unchanged", encoding="utf-8")

    for unsafe_target in ("/", f"{tmp_path}/..", str(target_symlink), str(existing_file)):
        result = subprocess.run(
            [str(RESTORE), "--archive", str(archive), "--target-data", unsafe_target],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 64, result.stderr
        assert file_manifest(target) == before


def test_restore_rejects_symlink_archive_without_mutating_target(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "safe.tar.gz", [("data", b"", tarfile.DIRTYPE, None)])
    archive_link = tmp_path / "safe-link.tar.gz"
    archive_link.symlink_to(archive)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    before = file_manifest(target)

    result = subprocess.run(
        [str(RESTORE), "--archive", str(archive_link), "--target-data", str(target)], text=True, capture_output=True, check=False
    )

    assert result.returncode == 64, result.stderr
    assert file_manifest(target) == before


def test_restore_rejects_caller_controlled_symlink_archive_ancestor_without_mutating_target(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-archive-parent"
    real_parent.mkdir()
    write_archive(real_parent / "safe.tar.gz", [("data", b"", tarfile.DIRTYPE, None)])
    archive_alias = tmp_path / "archive-alias"
    archive_alias.symlink_to(real_parent, target_is_directory=True)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    before = file_manifest(target)

    result = subprocess.run(
        [str(RESTORE), "--archive", str(archive_alias / "safe.tar.gz"), "--target-data", str(target)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64, result.stderr
    assert file_manifest(target) == before


def test_restore_rejects_caller_controlled_symlink_target_ancestor_without_mutating_target(tmp_path: Path) -> None:
    archive = write_archive(tmp_path / "safe.tar.gz", [("data", b"", tarfile.DIRTYPE, None)])
    real_parent = tmp_path / "real-target-parent"
    real_parent.mkdir()
    target = real_parent / "target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    before = file_manifest(target)
    target_alias = tmp_path / "target-alias"
    target_alias.symlink_to(real_parent, target_is_directory=True)

    result = subprocess.run(
        [str(RESTORE), "--archive", str(archive), "--target-data", str(target_alias / "target")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64, result.stderr
    assert file_manifest(target) == before
