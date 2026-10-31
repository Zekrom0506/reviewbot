"""Finds related code for the functions a PR changed.

For every changed function we collect:
  * callers         - other code that mentions "function_name("
  * existing tests  - test files that mention the function
  * similar code    - nearest neighbours by embedding (shows conventions)
"""

from reviewbot.diff_parser import FileDiff, changed_function_names

MAX_CONTEXT_CHARS = 6000


def build_context(store, embedder, repo: str, file_diffs: list, top_k: int = 4) -> dict:
    """Returns {"text": prompt-ready context, "untested_functions": [...]}"""
    if store.chunk_count(repo) == 0:
        return {"text": "", "untested_functions": []}

    sections = []
    seen = set()
    untested = []

    for file_diff in file_diffs:
        file_diff: FileDiff
        names = changed_function_names(file_diff)
        if file_diff.path.split("/")[-1].startswith("test"):
            continue

        for name in names[:5]:
            callers = [chunk for chunk in store.find_text(repo, f"{name}(", 10)
                       if not (chunk.path == file_diff.path and chunk.name == name)]
            tests = [chunk for chunk in callers if chunk.is_test]
            callers = [chunk for chunk in callers if not chunk.is_test][:2]
            if not tests:
                untested.append({"file": file_diff.path, "function": name})
            for label, chunks in (("Caller of", callers), ("Existing test for", tests[:1])):
                for chunk in chunks:
                    key = (chunk.path, chunk.start_line)
                    if key in seen:
                        continue
                    seen.add(key)
                    sections.append(f"# {label} {name}: {chunk.path} lines {chunk.start_line}-{chunk.end_line}\n{chunk.content}")

        added_code = "\n".join(
            line.text for hunk in file_diff.hunks for line in hunk.lines if line.kind != "remove"
        )
        if added_code.strip():
            query_vector = embedder.embed([added_code[:2000]])[0]
            for chunk in store.search(repo, query_vector, top_k, exclude_path=file_diff.path):
                key = (chunk.path, chunk.start_line)
                if key in seen:
                    continue
                seen.add(key)
                sections.append(f"# Similar code: {chunk.path} lines {chunk.start_line}-{chunk.end_line}\n{chunk.content}")

    text = ""
    for section in sections:
        if len(text) + len(section) > MAX_CONTEXT_CHARS:
            break
        text += section + "\n\n"
    return {"text": text.strip(), "untested_functions": untested}
