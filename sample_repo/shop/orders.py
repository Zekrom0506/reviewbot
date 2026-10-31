"""Checkout: turns a cart into an order and charges the customer."""

import logging

from shop import db, inventory, payments

logger = logging.getLogger(__name__)


def place_order(connection, user_id: int, cart, discount_percent: int = 0) -> int:
    if cart.item_count() == 0:
        raise ValueError("Cart is empty")

    total = cart.total(discount_percent)
    reserved = []
    try:
        for product_id, item in cart.items.items():
            inventory.reserve_stock(connection, product_id, item["quantity"])
            reserved.append((product_id, item["quantity"]))
        order_id = db.execute(
            connection,
            "INSERT INTO orders (user_id, total_paise, status) VALUES (?, ?, ?)",
            (user_id, total, "pending"),
        )
        payments.charge(order_id, total)
    except Exception:
        for product_id, quantity in reserved:
            inventory.release_stock(connection, product_id, quantity)
        logger.exception("Order failed for user %s", user_id)
        raise

    db.execute(connection, "UPDATE orders SET status = ? WHERE id = ?", ("paid", order_id))
    return order_id


def get_order(connection, order_id: int, user_id: int):
    return db.fetch_one(
        connection,
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_id),
    )


def cancel_order(connection, order_id: int, user_id: int) -> bool:
    order = get_order(connection, order_id, user_id)
    if order is None or order["status"] != "pending":
        return False
    db.execute(connection, "UPDATE orders SET status = ? WHERE id = ?", ("cancelled", order_id))
    return True
