#!/usr/bin/env python3
"""Validate the current, heading-scoped operational documentation claims."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVER_ROOT.parent
SERVER_LIMITATIONS = SERVER_ROOT / "docs" / "13_KNOWN_LIMITATIONS_KR.md"
IOS_LIMITATIONS = REPOSITORY_ROOT / "ios" / "docs" / "12_KNOWN_LIMITATIONS_KR.md"


@dataclass(frozen=True)
class Rule:
    name: str
    path: Path
    scope: str
    pattern: str
    expected_matches: int = 1


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def headings(lines: list[str], level: int | None = None) -> list[str]:
    marker = re.compile(r"^(#{1,2})\s+.+$")
    return [
        line
        for line in lines
        if (match := marker.match(line)) and (level is None or len(match.group(1)) == level)
    ]


def h2_body(lines: list[str], heading: str) -> list[str]:
    start = next((index for index, line in enumerate(lines) if line == f"## {heading}"), None)
    if start is None:
        return []
    body: list[str] = []
    for line in lines[start + 1 :]:
        if re.match(r"^#{1,2}\s+", line):
            break
        body.append(line)
    return body


def lines_for(rule: Rule, lines: list[str]) -> list[str]:
    if rule.scope == "h1":
        return headings(lines, level=1)
    if rule.scope == "all-headings":
        return headings(lines)
    if rule.scope == "all-bullets":
        return [line for line in lines if line.startswith("- ")]
    if rule.scope.startswith("h2:"):
        return h2_body(lines, rule.scope.removeprefix("h2:"))
    raise ValueError(f"Unknown scope: {rule.scope}")


STALE_RULES = (
    Rule("server-old-title", SERVER_LIMITATIONS, "h1", r"^# .*v0\.7\.0$", 0),
    Rule("server-native-mobile-excluded", SERVER_LIMITATIONS, "h2:의도적으로 제외한 기능", r"^Native Mobile App$", 0),
    Rule("ios-old-v010-heading", IOS_LIMITATIONS, "all-headings", r"^## v0\.1\.0 제한$", 0),
    Rule("ios-old-v02-candidate-heading", IOS_LIMITATIONS, "all-headings", r"^## v0\.2 후보$", 0),
    Rule("ios-live-activity-absent", IOS_LIMITATIONS, "all-bullets", r"^- Live Activity 없음$", 0),
)

REQUIRED_RULES = (
    Rule("server-current-title", SERVER_LIMITATIONS, "h1", r"^# .*v0\.9\.0.*$"),
    Rule("server-unsigned-default", SERVER_LIMITATIONS, "h2:현재 제약", r".*ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=false.*"),
    Rule("server-native-ios-version", SERVER_LIMITATIONS, "h2:현재 제약", r".*native iOS v0\.2\.1.*"),
    Rule("ios-current-heading", IOS_LIMITATIONS, "all-headings", r"^## v0\.2\.1 현재 제한$"),
    Rule("ios-dead-letter-bullet", IOS_LIMITATIONS, "all-bullets", r"^- 오프라인 Capture는 .*dead-letter.*$"),
    Rule("ios-full-refresh-bullet", IOS_LIMITATIONS, "all-bullets", r"^- .*full refresh.*$"),
)


def match_count(rule: Rule) -> int:
    candidates = lines_for(rule, read_lines(rule.path))
    return sum(1 for line in candidates if re.fullmatch(rule.pattern, line))


def print_result(kind: str, rule: Rule, count: int) -> None:
    relative = rule.path.relative_to(REPOSITORY_ROOT).as_posix()
    print(
        f"{kind} name={rule.name} file={relative} scope={rule.scope} "
        f"matches={count} expected={rule.expected_matches}"
    )


def main() -> int:
    stale_count = 0
    required_count = 0
    failures: list[str] = []

    for rule in STALE_RULES:
        count = match_count(rule)
        print_result("STALE", rule, count)
        stale_count += count
        if count != rule.expected_matches:
            failures.append(rule.name)

    for rule in REQUIRED_RULES:
        count = match_count(rule)
        print_result("REQUIRED", rule, count)
        if count == rule.expected_matches:
            required_count += 1
        else:
            failures.append(rule.name)

    if failures:
        print(
            f"DOCS_CHECK_FAILED stale_count={stale_count} required_count={required_count} "
            f"failures={','.join(failures)}",
            file=sys.stderr,
        )
        return 1
    print(f"DOCS_CHECK_OK stale_count={stale_count} required_count={required_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
