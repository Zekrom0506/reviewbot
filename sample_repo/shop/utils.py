"""Small helpers used across the shop."""

import re


def paginate(items: list, page: int, page_size: int = 10) -> list:
    if page < 1:
        raise ValueError("Pages start at 1")
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def format_rupees(paise: int) -> str:
    rupees = paise // 100
    remainder = paise % 100
    return f"₹{rupees:,}.{remainder:02d}"


def chunk(items: list, size: int) -> list:
    if size <= 0:
        raise ValueError("Size must be positive")
    return [items[index:index + size] for index in range(0, len(items), size)]
