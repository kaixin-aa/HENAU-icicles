#!/usr/bin/env python3
"""Dependency-free safety and structure checks for HENAU-icicles."""

from __future__ import annotations

import argparse
import dataclasses
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Iterable


MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_PATH_LENGTH = 180
MAX_TEXT_SCAN_SIZE = 2 * 1024 * 1024

COURSES = ("线性代数", "数据结构")
REQUIRED_ROOT_FILES = (
    "README.md", "CONTRIBUTING.md", "CONTENT_POLICY.md", "LICENSE",
    "LICENSE-CODE", "LICENSE_SCOPE.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md",
)
REQUIRED_COURSE_FILES = (
    "README.md", "攻略/学习指南.md", "考试/模拟卷.md", "考试/学生解答.md",
)

ROOT_IGNORED_DIRS = {".git", ".pytest_cache", "__pycache__", "_site", "reports"}
CACHE_DIRS = {".mypy_cache", ".ruff_cache", "__pycache__"}
BANNED_DIRS = {
    ".conda", ".idea", ".venv", ".vs", "build", "dist", "node_modules",
    "target", "venv",
}
BANNED_EXTENSIONS = {
    ".7z", ".apk", ".bz2", ".com", ".dll", ".dmg", ".docm", ".dotm",
    ".exe", ".gz", ".img", ".iso", ".jar", ".msi", ".p12", ".pem",
    ".pfx", ".potm", ".ppam", ".ppsm", ".pptm", ".rar", ".scr",
    ".sldm", ".tar", ".xlam", ".xll", ".xlsm", ".xltm", ".xz", ".zip",
}
TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".css", ".go", ".h", ".html", ".java",
    ".js", ".json", ".jsx", ".md", ".py", ".rs", ".tex", ".toml",
    ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
TEXT_SCAN_SKIPPED_ROOTS = {"tests", "tools"}

PII_PATTERNS = {
    "possible Chinese mobile number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "possible Chinese identity number": re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "assigned credential": re.compile(
        r"(?i)\b(?:api[_-]?key|password|passwd|secret|access[_-]?token)\b"
        r"\s*[:=]\s*[\"']?[^\s\"']{8,}"
    ),
}
LOCAL_PATH_PATTERN = re.compile(r"(?i)(?:^|[\s`\"'])\b[A-Z]:\\")
MARKDOWN_LINK = re.compile(
    r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)"
)


@dataclasses.dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str


@dataclasses.dataclass
class AuditResult:
    issues: list[Issue] = dataclasses.field(default_factory=list)
    files_checked: int = 0

    def add(self, code: str, path: str | Path, message: str) -> None:
        rendered = path.as_posix() if isinstance(path, Path) else str(path)
        self.issues.append(Issue(code, rendered, message))

    @property
    def ok(self) -> bool:
        return not self.issues


def _strip_fenced_code(text: str) -> str:
    return re.sub(r"```.*?```|~~~.*?~~~", "", text, flags=re.DOTALL)


def _repository_files(root: Path, result: AuditResult) -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        kept: list[str] = []
        for dirname in sorted(dirnames, key=str.casefold):
            candidate = directory_path / dirname
            relative = candidate.relative_to(root)
            folded = dirname.casefold()
            if len(relative.parts) == 1 and folded in ROOT_IGNORED_DIRS:
                continue
            if candidate.is_symlink():
                result.add("symlink", relative, "directory symlinks are not allowed")
                continue
            if folded in BANNED_DIRS:
                result.add("banned-directory", relative, f"directory {dirname!r} is not allowed")
                continue
            if folded in CACHE_DIRS:
                if relative.parts and relative.parts[0] in COURSES:
                    result.add("banned-directory", relative, "cache directory is not allowed in a course")
                continue
            kept.append(dirname)
        dirnames[:] = kept
        for filename in sorted(filenames, key=str.casefold):
            candidate = directory_path / filename
            relative = candidate.relative_to(root)
            if candidate.is_symlink():
                result.add("symlink", relative, "file symlinks are not allowed")
                continue
            files.append(candidate)
    return files


def _check_markdown_links(path: Path, relative: Path, root: Path, result: AuditResult) -> None:
    try:
        text = _strip_fenced_code(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError):
        return
    for match in MARKDOWN_LINK.finditer(text):
        raw = match.group(1).strip("<>")
        split = urllib.parse.urlsplit(raw)
        if split.scheme in {"http", "https", "mailto"} or raw.startswith("#"):
            continue
        if split.scheme or split.netloc:
            result.add("unsafe-link", relative, f"unsupported link target: {raw}")
            continue
        decoded = urllib.parse.unquote(split.path)
        if not decoded:
            continue
        target = (path.parent / decoded).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            result.add("broken-link", relative, f"link escapes repository: {raw}")
            continue
        if not target.exists():
            result.add("broken-link", relative, f"target does not exist: {raw}")


def _check_sensitive_text(path: Path, relative: Path, result: AuditResult) -> None:
    if path.suffix.casefold() not in TEXT_EXTENSIONS or path.stat().st_size > MAX_TEXT_SCAN_SIZE:
        return
    if relative.parts and relative.parts[0] in TEXT_SCAN_SKIPPED_ROOTS:
        return
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            result.add("possible-pii", relative, label)
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            result.add("possible-secret", relative, label)
    if LOCAL_PATH_PATTERN.search(text):
        result.add("absolute-local-path", relative, "absolute Windows path must not be published")


def _check_required_content(root: Path, result: AuditResult) -> None:
    for value in REQUIRED_ROOT_FILES:
        path = root / value
        if not path.is_file():
            result.add("required-file", value, "required root file is missing")

    readme = root / "README.md"
    root_text = readme.read_text(encoding="utf-8-sig") if readme.is_file() else ""
    for course in COURSES:
        course_root = root / course
        for value in REQUIRED_COURSE_FILES:
            path = course_root / Path(*value.split("/"))
            if not path.is_file():
                result.add("required-course-file", path.relative_to(root), "required course example is missing")
        if f"./{course}/" not in root_text:
            result.add("course-navigation", "README.md", f"root README must link to {course}")
        course_readme = course_root / "README.md"
        course_text = course_readme.read_text(encoding="utf-8-sig") if course_readme.is_file() else ""
        for target in ("攻略/学习指南.md", "考试/模拟卷.md", "考试/学生解答.md"):
            if target not in course_text:
                result.add("course-navigation", course_readme.relative_to(root), f"README must link to {target}")
        paper = course_root / "考试" / "模拟卷.md"
        paper_text = paper.read_text(encoding="utf-8-sig") if paper.is_file() else ""
        if "项目结构演示，不是真实历年试卷" not in paper_text:
            result.add("exam-disclaimer", paper.relative_to(root), "practice paper disclaimer is required")
        solution = course_root / "考试" / "学生解答.md"
        solution_text = solution.read_text(encoding="utf-8-sig") if solution.is_file() else ""
        if "非标准答案，仅供复习核对" not in solution_text:
            result.add("solution-disclaimer", solution.relative_to(root), "student solution disclaimer is required")


def audit_repository(
    root: Path,
    *,
    max_file_size: int = MAX_FILE_SIZE,
    max_path_length: int = MAX_PATH_LENGTH,
) -> AuditResult:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    result = AuditResult()
    files = _repository_files(root, result)
    result.files_checked = len(files)
    _check_required_content(root, result)
    for path in files:
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        try:
            size = path.stat().st_size
        except OSError as exc:
            result.add("unreadable-file", relative, str(exc))
            continue
        if size > max_file_size:
            result.add("file-too-large", relative, f"{size} bytes exceeds {max_file_size}")
        if len(relative_text) > max_path_length:
            result.add("path-too-long", relative, f"path length {len(relative_text)} exceeds {max_path_length}")
        if path.suffix.casefold() in BANNED_EXTENSIONS:
            result.add("banned-extension", relative, f"extension {path.suffix!r} is not allowed")
        if path.suffix.casefold() == ".md":
            _check_markdown_links(path, relative, root, result)
        _check_sensitive_text(path, relative, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--max-file-size", type=int, default=MAX_FILE_SIZE)
    parser.add_argument("--max-path-length", type=int, default=MAX_PATH_LENGTH)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        result = audit_repository(
            args.root,
            max_file_size=args.max_file_size,
            max_path_length=args.max_path_length,
        )
    except (OSError, ValueError) as exc:
        print(f"check error: {exc}", file=sys.stderr)
        return 2
    for issue in result.issues:
        print(f"::error file={issue.path}::{issue.code}: {issue.message}")
    print(f"checked {result.files_checked} files; {len(result.issues)} error(s)")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
