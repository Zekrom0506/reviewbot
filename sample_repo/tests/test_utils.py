from shop.utils import format_rupees, paginate, slugify


def test_paginate():
    assert paginate(list(range(25)), 3) == [20, 21, 22, 23, 24]


def test_slugify():
    assert slugify("  Hello, World! ") == "hello-world"


def test_format_rupees():
    assert format_rupees(123456) == "₹1,234.56"
