"""Shopping cart. Prices are stored in paise (1 rupee = 100 paise)."""

MAX_QUANTITY_PER_ITEM = 10


class Cart:
    def __init__(self):
        self.items = {}  # product_id -> {"price": paise, "quantity": n}

    def add_item(self, product_id: int, price_paise: int, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        current = self.items.get(product_id, {"price": price_paise, "quantity": 0})
        new_quantity = current["quantity"] + quantity
        if new_quantity > MAX_QUANTITY_PER_ITEM:
            raise ValueError(f"At most {MAX_QUANTITY_PER_ITEM} of one item")
        self.items[product_id] = {"price": price_paise, "quantity": new_quantity}

    def remove_item(self, product_id: int) -> None:
        self.items.pop(product_id, None)

    def subtotal(self) -> int:
        total = 0
        for item in self.items.values():
            total += item["price"] * item["quantity"]
        return total

    def total(self, discount_percent: int = 0) -> int:
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("Discount must be between 0 and 100")
        subtotal = self.subtotal()
        discount = subtotal * discount_percent // 100
        return subtotal - discount

    def item_count(self) -> int:
        return sum(item["quantity"] for item in self.items.values())
