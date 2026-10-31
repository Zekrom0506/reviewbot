"""Splits source files into small pieces ("chunks") worth embedding.

For Python we use the built-in ast module to cut exactly one chunk per
function or method. For other languages we use windows of 40 lines.
"""

import ast
from dataclasses import dataclass

INDEXED_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb")
MAX_FILE_BYTES = 200_000
WINDOW_LINES = 40


@dataclass
class CodeChunk:
    path: str
    name: str
    start_line: int
    end_line: int
    content: str

    @property
    def is_test(self) -> bool:
        lowered = self.path.lower()
        return "test" in lowered.split("/")[-1] or "/tests/" in "/" + lowered or lowered.startswith("tests/")


def should_index(path: str, size: int = 0) -> bool:
    if not path.endswith(INDEXED_EXTENSIONS):
        return False
    if size and size > MAX_FILE_BYTES:
        return False
    skip_folders = ("node_modules/", "vendor/", "dist/", "build/", ".venv/", "venv/")
    return not any(folder in path for folder in skip_folders)


def chunk_python(path: str, source: str) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_by_window(path, source)

    lines = source.splitlines()
    chunks = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            if node.decorator_list:
                start = min(decorator.lineno for decorator in node.decorator_list)
            end = node.end_lineno or node.lineno
            content = "\n".join(lines[start - 1:end])
            chunks.append(CodeChunk(path, node.name, start, end, content))

    if not chunks:
        return chunk_by_window(path, source)
    return chunks


def chunk_by_window(path: str, source: str) -> list:
    lines = source.splitlines()
    chunks = []
    for start in range(0, len(lines), WINDOW_LINES):
        piece = lines[start:start + WINDOW_LINES]
        if not any(line.strip() for line in piece):
            continue
        name = f"{path.split('/')[-1]}:{start + 1}"
        chunks.append(CodeChunk(path, name, start + 1, start + len(piece), "\n".join(piece)))
    return chunks


def chunk_file(path: str, source: str) -> list:
    if path.endswith(".py"):
        return chunk_python(path, source)
    return chunk_by_window(path, source)
