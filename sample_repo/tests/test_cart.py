import pytest

from shop.cart import Cart


def test_total_with_discount():
    cart = Cart()
    cart.add_item(1, 1000, 2)
    assert cart.total(10) == 1800


def test_quantity_limit():
    cart = Cart()
    with pytest.raises(ValueError):
        cart.add_item(1, 1000, 11)


def test_remove_item():
    cart = Cart()
    cart.add_item(1, 500)
    cart.remove_item(1)
    assert cart.item_count() == 0
