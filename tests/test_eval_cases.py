"""Makes sure every evaluation case applies cleanly to the sample repo and
that every seeded bug sits on a line the bot is allowed to comment on."""

import pytest

from eval.build import build_case_diff, bug_line_numbers, load_sample_repo
from eval.cases import ALL_CASES
from reviewbot.diff_parser import parse_diff

BASE_FILES = load_sample_repo()


@pytest.mark.parametrize("case", ALL_CASES, ids=[case["id"] for case in ALL_CASES])
def test_case_is_valid(case):
    diff_text, changed = build_case_diff(BASE_FILES, case)
    file_diffs = {file_diff.path: file_diff for file_diff in parse_diff(diff_text)}
    assert set(file_diffs) == set(changed)
    for path, line in bug_line_numbers(changed, case):
        assert line in file_diffs[path].commentable_line_numbers(), f"{case['id']}: bug line {line} not in diff"


def test_case_ids_are_unique():
    ids = [case["id"] for case in ALL_CASES]
    assert len(ids) == len(set(ids))
