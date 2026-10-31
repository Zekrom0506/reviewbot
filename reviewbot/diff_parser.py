"""Turns a unified diff (the text GitHub shows for a PR) into Python objects.

A diff looks like this:

    diff --git a/app.py b/app.py
    --- a/app.py
    +++ b/app.py
    @@ -10,3 +10,4 @@ def login():
         user = find_user(name)
    -    return user
    +    if user is None:
    +        return None
    +    return user

Lines starting with "+" were added, "-" were removed, " " are unchanged.
The "@@ -10,3 +10,4 @@" header says where the hunk starts in the old and
new file. We track line numbers so the bot can comment on exact lines.
"""

import re
from dataclasses import dataclass, field

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class DiffLine:
    kind: str  # "add", "remove" or "context"
    text: str
    old_number: int | None
    new_number: int | None


@dataclass
class Hunk:
    old_start: int
    new_start: int
    header: str
    lines: list = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    old_path: str
    status: str = "modified"  # "added", "removed", "modified", "renamed"
    hunks: list = field(default_factory=list)
    is_binary: bool = False

    def added_line_numbers(self) -> set:
        numbers = set()
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "add":
                    numbers.add(line.new_number)
        return numbers

    def commentable_line_numbers(self) -> set:
        """Lines on the new side that GitHub lets us comment on."""
        numbers = set()
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.new_number is not None:
                    numbers.add(line.new_number)
        return numbers

    def changed_line_count(self) -> int:
        count = 0
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind != "context":
                    count += 1
        return count

    def to_text(self) -> str:
        """Rebuild the diff text with new-file line numbers, which helps the
        LLM report the correct line."""
        output = [f"File: {self.path} ({self.status})"]
        for hunk in self.hunks:
            output.append(f"@@ {hunk.header.strip()}")
            for line in hunk.lines:
                if line.kind == "add":
                    output.append(f"{line.new_number:>5} + {line.text}")
                elif line.kind == "remove":
                    output.append(f"{'':>5} - {line.text}")
                else:
                    output.append(f"{line.new_number:>5}   {line.text}")
        return "\n".join(output)


def parse_diff(diff_text: str) -> list:
    files = []
    current_file = None
    current_hunk = None
    old_line = 0
    new_line = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            parts = raw_line.split(" ")
            old_path = parts[2][2:] if len(parts) > 2 else ""
            new_path = parts[3][2:] if len(parts) > 3 else old_path
            current_file = FileDiff(path=new_path, old_path=old_path)
            files.append(current_file)
            current_hunk = None
            continue

        if current_file is None:
            continue

        if raw_line.startswith("new file mode"):
            current_file.status = "added"
        elif raw_line.startswith("deleted file mode"):
            current_file.status = "removed"
        elif raw_line.startswith("rename from"):
            current_file.status = "renamed"
        elif raw_line.startswith("Binary files"):
            current_file.is_binary = True
        elif raw_line.startswith("--- ") and current_hunk is None:
            continue
        elif raw_line.startswith("+++ ") and current_hunk is None:
            target = raw_line[4:].strip()
            if target.startswith("b/"):
                current_file.path = target[2:]
        elif raw_line.startswith("@@"):
            match = HUNK_HEADER.match(raw_line)
            if match is None:
                continue
            old_line = int(match.group(1))
            new_line = int(match.group(3))
            current_hunk = Hunk(old_start=old_line, new_start=new_line, header=raw_line)
            current_file.hunks.append(current_hunk)
        elif current_hunk is not None:
            if raw_line.startswith("+"):
                current_hunk.lines.append(DiffLine("add", raw_line[1:], None, new_line))
                new_line += 1
            elif raw_line.startswith("-"):
                current_hunk.lines.append(DiffLine("remove", raw_line[1:], old_line, None))
                old_line += 1
            elif raw_line.startswith("\\"):
                # "\ No newline at end of file"
                continue
            else:
                text = raw_line[1:] if raw_line.startswith(" ") else raw_line
                current_hunk.lines.append(DiffLine("context", text, old_line, new_line))
                old_line += 1
                new_line += 1

    return files


def chunk_files(files: list, max_lines: int) -> list:
    """Group file diffs into chunks so each LLM call stays small.

    A very large single file is split hunk by hunk.
    Returns a list of chunks, where each chunk is a list of FileDiff objects.
    """
    chunks = []
    current_chunk = []
    current_size = 0

    for file_diff in files:
        size = file_diff.changed_line_count()

        if size > max_lines and len(file_diff.hunks) > 1:
            # Split this big file into several smaller FileDiffs.
            piece = FileDiff(file_diff.path, file_diff.old_path, file_diff.status)
            piece_size = 0
            for hunk in file_diff.hunks:
                hunk_size = sum(1 for line in hunk.lines if line.kind != "context")
                if piece_size + hunk_size > max_lines and piece.hunks:
                    chunks.append([piece])
                    piece = FileDiff(file_diff.path, file_diff.old_path, file_diff.status)
                    piece_size = 0
                piece.hunks.append(hunk)
                piece_size += hunk_size
            if piece.hunks:
                chunks.append([piece])
            continue

        if current_size + size > max_lines and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(file_diff)
        current_size += size

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def changed_function_names(file_diff: FileDiff) -> list:
    """Best-effort list of functions touched by the diff, read from hunk
    headers and from added 'def'/'function' lines."""
    names = []
    patterns = [
        re.compile(r"def\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\("),
    ]
    for hunk in file_diff.hunks:
        texts = [hunk.header] + [line.text for line in hunk.lines if line.kind != "remove"]
        for text in texts:
            for pattern in patterns:
                for match in pattern.finditer(text):
                    name = match.group(1)
                    if name not in names:
                        names.append(name)
    return names
