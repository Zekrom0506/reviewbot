"""Turns an evaluation case into a diff, like the one GitHub would send."""

import difflib
from pathlib import Path

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"


def load_sample_repo() -> dict:
    files = {}
    for path in sorted(SAMPLE_REPO.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files[str(path.relative_to(SAMPLE_REPO))] = path.read_text(encoding="utf-8")
    return files


def apply_case(base_files: dict, case: dict) -> dict:
    """Returns {path: new content} for every file the case changes."""
    changed = {}
    for path, find, replace in case["edits"]:
        current = changed.get(path, base_files.get(path))
        if find == "":
            if current is not None:
                raise ValueError(f"{case['id']}: {path} already exists")
            changed[path] = replace
            continue
        if current is None:
            raise ValueError(f"{case['id']}: {path} does not exist")
        if current.count(find) != 1:
            raise ValueError(f"{case['id']}: text to replace found {current.count(find)} times in {path}")
        changed[path] = current.replace(find, replace)
    return changed


def make_git_diff(path: str, old: str | None, new: str) -> str:
    old_lines = old.splitlines() if old is not None else []
    new_lines = new.splitlines()
    from_name = f"a/{path}" if old is not None else "/dev/null"
    lines = [f"diff --git a/{path} b/{path}"]
    if old is None:
        lines.append("new file mode 100644")
    body = list(difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=f"b/{path}", n=3, lineterm=""))
    lines.extend(body)
    return "\n".join(lines)


def build_case_diff(base_files: dict, case: dict) -> tuple:
    """Returns (diff_text, changed_files)."""
    changed = apply_case(base_files, case)
    parts = [make_git_diff(path, base_files.get(path), content) for path, content in changed.items()]
    return "\n".join(parts) + "\n", changed


def bug_line_numbers(changed: dict, case: dict) -> list:
    """Returns [(file, line_number)] for each seeded bug."""
    results = []
    for path, text in case["bugs"]:
        matches = [number for number, line in enumerate(changed[path].splitlines(), start=1) if text in line]
        if len(matches) != 1:
            raise ValueError(f"{case['id']}: bug marker {text!r} matched {len(matches)} lines in {path}")
        results.append((path, matches[0]))
    return results
