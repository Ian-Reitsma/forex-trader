"""Fail when tracked text files contain credential-shaped environment assignments."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ASSIGNMENT_PATTERNS = (
    re.compile(r"(?i)OANDA_API_TOKEN\s*=\s*[a-f0-9]{24,}-[a-f0-9]{24,}"),
    re.compile(r"(?i)Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{24,}"),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def main() -> None:
    findings: list[str] = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(text) for pattern in ASSIGNMENT_PATTERNS):
            findings.append(str(path))
    if findings:
        joined = ", ".join(sorted(findings))
        raise SystemExit(f"credential-shaped value detected in tracked files: {joined}")
    print("no credential-shaped values detected in tracked text files")


if __name__ == "__main__":
    main()
