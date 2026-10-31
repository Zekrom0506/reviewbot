"""Stock management."""

from shop import db


class OutOfStockError(Exception):
    pass


def get_stock(connection, product_id: int) -> int:
    row = db.fetch_one(connection, "SELECT stock FROM products WHERE id = ?", (product_id,))
    if row is None:
        raise KeyError(f"Unknown product {product_id}")
    return row["stock"]


def reserve_stock(connection, product_id: int, quantity: int) -> None:
    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    available = get_stock(connection, product_id)
    if available < quantity:
        raise OutOfStockError(f"Only {available} left")
    db.execute(
        connection,
        "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
        (quantity, product_id, quantity),
    )


def release_stock(connection, product_id: int, quantity: int) -> None:
    db.execute(connection, "UPDATE products SET stock = stock + ? WHERE id = ?", (quantity, product_id))


def search_products(connection, name: str, limit: int = 20) -> list:
    return db.fetch_all(
        connection,
        "SELECT * FROM products WHERE name LIKE ? ORDER BY name LIMIT ?",
        (f"%{name}%", limit),
    )
