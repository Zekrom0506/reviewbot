"""The evaluation set: pull requests against sample_repo with KNOWN bugs.

Each case is one pull request:
  id        short name
  title     PR title the bot sees
  edits     list of (file, find, replace). find="" means "create a new file"
            whose content is replace.
  bugs      list of (file, text). Each text appears on exactly one line of
            the changed file; that line is where the seeded bug is. A case
            with no bugs is a "clean" PR: any comment on it is a false alarm.

These same cases are opened as real PRs by scripts/seed_sample_repo.py.
"""

BUGGY_CASES = [
    # ---------------------------------------------------------------- auth
    {
        "id": "auth-sql-injection",
        "title": "Simplify user lookup query",
        "edits": [("shop/auth.py",
                   'return db.fetch_one(connection, "SELECT * FROM users WHERE email = ?", (email.lower(),))',
                   'return db.fetch_one(connection, f"SELECT * FROM users WHERE email = \'{email.lower()}\'")')],
        "bugs": [("shop/auth.py", "f\"SELECT * FROM users WHERE email")],
    },
    {
        "id": "auth-password-length-inverted",
        "title": "Tweak password validation",
        "edits": [("shop/auth.py", "if len(password) < 8:", "if len(password) > 8:")],
        "bugs": [("shop/auth.py", "if len(password) > 8:")],
    },
    {
        "id": "auth-timing-compare",
        "title": "Simplify password verification",
        "edits": [("shop/auth.py", "return hmac.compare_digest(digest.hex(), digest_hex)", "return digest.hex() == digest_hex")],
        "bugs": [("shop/auth.py", "return digest.hex() == digest_hex")],
    },
    {
        "id": "auth-login-skips-password-check",
        "title": "Allow admins to log in faster",
        "edits": [("shop/auth.py",
                   'if not verify_password(password, user["password_hash"]):',
                   'if not verify_password(password, user["password_hash"]) and not user["is_admin"]:')],
        "bugs": [("shop/auth.py", 'and not user["is_admin"]:')],
    },
    {
        "id": "auth-session-expiry-inverted",
        "title": "Fix session expiry handling",
        "edits": [("shop/auth.py", 'if session["expires_at"] < time.time():', 'if session["expires_at"] > time.time():')],
        "bugs": [("shop/auth.py", 'if session["expires_at"] > time.time():')],
    },
    {
        "id": "auth-admin-check-bypass",
        "title": "Refactor admin check",
        "edits": [("shop/auth.py", 'if user is None or not user["is_admin"]:', 'if user is not None and not user["is_admin"]:')],
        "bugs": [("shop/auth.py", 'if user is not None and not user["is_admin"]:')],
    },
    {
        "id": "auth-hardcoded-key",
        "title": "Add admin API key for internal tools",
        "edits": [("shop/auth.py", "PBKDF2_ROUNDS = 200_000",
                   'PBKDF2_ROUNDS = 200_000\nADMIN_API_KEY = "sk_live_51HxT9aQ2mPz8Rk3Vn7Yc0WdLq"')],
        "bugs": [("shop/auth.py", "ADMIN_API_KEY = ")],
    },
    {
        "id": "auth-logs-password",
        "title": "Add debug output to login",
        "edits": [("shop/auth.py", "    user = find_user_by_email(connection, email)\n    if user is None:\n        return None\n    if not",
                   '    print(f"Login attempt for {email} with password {password}")\n'
                   "    user = find_user_by_email(connection, email)\n    if user is None:\n        return None\n    if not")],
        "bugs": [("shop/auth.py", 'print(f"Login attempt')],
    },
    {
        "id": "auth-md5-passwords",
        "title": "Speed up password hashing",
        "edits": [("shop/auth.py",
                   '    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)\n    return salt.hex()',
                   '    digest = hashlib.md5(salt + password.encode("utf-8")).digest()\n    return salt.hex()')],
        "bugs": [("shop/auth.py", "digest = hashlib.md5(")],
    },
    {
        "id": "auth-predictable-token",
        "title": "Use simpler session tokens",
        "edits": [("shop/auth.py", "token = secrets.token_urlsafe(32)", 'token = str(user["id"]) + "-" + str(int(time.time()))')],
        "bugs": [("shop/auth.py", 'token = str(user["id"])')],
    },
    # ---------------------------------------------------------------- cart
    {
        "id": "cart-float-money",
        "title": "Make discount calculation more precise",
        "edits": [("shop/cart.py", "discount = subtotal * discount_percent // 100", "discount = subtotal * discount_percent / 100")],
        "bugs": [("shop/cart.py", "discount = subtotal * discount_percent / 100")],
    },
    {
        "id": "cart-allows-zero-quantity",
        "title": "Relax quantity validation",
        "edits": [("shop/cart.py", "if quantity <= 0:", "if quantity < 0:")],
        "bugs": [("shop/cart.py", "if quantity < 0:")],
    },
    {
        "id": "cart-off-by-one-limit",
        "title": "Enforce max quantity",
        "edits": [("shop/cart.py", "if new_quantity > MAX_QUANTITY_PER_ITEM:", "if new_quantity >= MAX_QUANTITY_PER_ITEM:")],
        "bugs": [("shop/cart.py", "if new_quantity >= MAX_QUANTITY_PER_ITEM:")],
    },
    {
        "id": "cart-overwrites-quantity",
        "title": "Simplify add_item",
        "edits": [("shop/cart.py", 'new_quantity = current["quantity"] + quantity', "new_quantity = quantity")],
        "bugs": [("shop/cart.py", "new_quantity = quantity")],
    },
    {
        "id": "cart-subtotal-ignores-quantity",
        "title": "Optimise subtotal loop",
        "edits": [("shop/cart.py", 'total += item["price"] * item["quantity"]', 'total += item["price"]')],
        "bugs": [("shop/cart.py", 'total += item["price"]')],
    },
    # ------------------------------------------------------------ payments
    {
        "id": "payments-verify-false",
        "title": "Work around gateway certificate issue",
        "edits": [("shop/payments.py",
                   'json={"order_id": order_id, "amount": amount_paise, "currency": "INR"},',
                   'json={"order_id": order_id, "amount": amount_paise, "currency": "INR"},\n            verify=False,')],
        "bugs": [("shop/payments.py", "verify=False,")],
    },
    {
        "id": "payments-refund-swallows-error",
        "title": "Make refunds more resilient",
        "edits": [("shop/payments.py", '        raise PaymentError("Refund failed") from error', "        return True")],
        "bugs": [("shop/payments.py", "        return True")],
    },
    {
        "id": "payments-zero-charge",
        "title": "Allow free orders",
        "edits": [("shop/payments.py", '    if amount_paise <= 0:\n        raise PaymentError("Amount must be positive")',
                   '    if amount_paise < 0:\n        raise PaymentError("Amount must be positive")')],
        "bugs": [("shop/payments.py", "if amount_paise < 0:")],
    },
    {
        "id": "payments-logs-key",
        "title": "Log gateway configuration",
        "edits": [("shop/payments.py", "def charge(order_id: int, amount_paise: int) -> str:\n",
                   'def charge(order_id: int, amount_paise: int) -> str:\n    logger.info("Charging order %s using key %s", order_id, GATEWAY_KEY)\n')],
        "bugs": [("shop/payments.py", 'logger.info("Charging order %s using key')],
    },
    {
        "id": "payments-rupees-float",
        "title": "Send amount in rupees",
        "edits": [("shop/payments.py",
                   'json={"order_id": order_id, "amount": amount_paise, "currency": "INR"},',
                   'json={"order_id": order_id, "amount": amount_paise / 100, "currency": "INR"},')],
        "bugs": [("shop/payments.py", '"amount": amount_paise / 100')],
    },
    # ----------------------------------------------------------- inventory
    {
        "id": "inventory-search-injection",
        "title": "Simplify product search",
        "edits": [("shop/inventory.py",
                   '        "SELECT * FROM products WHERE name LIKE ? ORDER BY name LIMIT ?",\n        (f"%{name}%", limit),',
                   '        f"SELECT * FROM products WHERE name LIKE \'%{name}%\' ORDER BY name LIMIT ?",\n        (limit,),')],
        "bugs": [("shop/inventory.py", "f\"SELECT * FROM products WHERE name LIKE")],
    },
    {
        "id": "inventory-race-condition",
        "title": "Clean up stock update query",
        "edits": [("shop/inventory.py",
                   '        "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",\n        (quantity, product_id, quantity),',
                   '        "UPDATE products SET stock = stock - ? WHERE id = ?",\n        (quantity, product_id),')],
        "bugs": [("shop/inventory.py", '"UPDATE products SET stock = stock - ? WHERE id = ?",')],
    },
    {
        "id": "inventory-last-item",
        "title": "Stricter stock check",
        "edits": [("shop/inventory.py", "if available < quantity:", "if available <= quantity:")],
        "bugs": [("shop/inventory.py", "if available <= quantity:")],
    },
    {
        "id": "inventory-release-subtracts",
        "title": "Refactor release_stock",
        "edits": [("shop/inventory.py", '"UPDATE products SET stock = stock + ? WHERE id = ?"', '"UPDATE products SET stock = stock - ? WHERE id = ?"')],
        "bugs": [("shop/inventory.py", 'db.execute(connection, "UPDATE products SET stock = stock - ? WHERE id = ?"')],
    },
    {
        "id": "inventory-unknown-product-zero",
        "title": "Avoid exceptions for unknown products",
        "edits": [("shop/inventory.py", '        raise KeyError(f"Unknown product {product_id}")', "        return 0")],
        "bugs": [("shop/inventory.py", "        return 0")],
    },
    # --------------------------------------------------------------- utils
    {
        "id": "utils-paginate-off-by-one",
        "title": "Simplify pagination math",
        "edits": [("shop/utils.py", "start = (page - 1) * page_size", "start = page * page_size")],
        "bugs": [("shop/utils.py", "start = page * page_size")],
    },
    {
        "id": "utils-parse-int-returns-input",
        "title": "Return original value when parsing fails",
        "edits": [("shop/utils.py", "    except (TypeError, ValueError):\n        return default",
                   "    except (TypeError, ValueError):\n        return value")],
        "bugs": [("shop/utils.py", "        return value")],
    },
    {
        "id": "utils-format-rupees-float",
        "title": "Simplify rupee formatting",
        "edits": [("shop/utils.py", "rupees = paise // 100", "rupees = paise / 100")],
        "bugs": [("shop/utils.py", "rupees = paise / 100")],
    },
    {
        "id": "utils-chunk-skips-items",
        "title": "Tidy chunk helper",
        "edits": [("shop/utils.py", "for index in range(0, len(items), size)]", "for index in range(0, len(items), size + 1)]")],
        "bugs": [("shop/utils.py", "range(0, len(items), size + 1)")],
    },
    {
        "id": "utils-parse-int-eval",
        "title": "Support expressions in numeric inputs",
        "edits": [("shop/utils.py", "        return int(value)", "        return int(eval(value))")],
        "bugs": [("shop/utils.py", "return int(eval(value))")],
    },
    # -------------------------------------------------------------- orders
    {
        "id": "orders-swallows-failure",
        "title": "Do not crash checkout on payment errors",
        "edits": [("shop/orders.py",
                   "        for product_id, quantity in reserved:\n            inventory.release_stock(connection, product_id, quantity)\n"
                   '        logger.exception("Order failed for user %s", user_id)\n        raise',
                   '        logger.exception("Order failed for user %s", user_id)\n        return -1')],
        "bugs": [("shop/orders.py", "        return -1")],
    },
    {
        "id": "orders-idor",
        "title": "Simplify order lookup",
        "edits": [("shop/orders.py",
                   '        "SELECT * FROM orders WHERE id = ? AND user_id = ?",\n        (order_id, user_id),',
                   '        "SELECT * FROM orders WHERE id = ?",\n        (order_id,),')],
        "bugs": [("shop/orders.py", '"SELECT * FROM orders WHERE id = ?",')],
    },
    {
        "id": "orders-cancel-paid",
        "title": "Allow more orders to be cancelled",
        "edits": [("shop/orders.py", 'if order is None or order["status"] != "pending":', 'if order is None or order["status"] == "cancelled":')],
        "bugs": [("shop/orders.py", 'order["status"] == "cancelled":')],
    },
    {
        "id": "orders-ignores-discount",
        "title": "Compute order total from cart",
        "edits": [("shop/orders.py", "total = cart.total(discount_percent)", "total = cart.subtotal()")],
        "bugs": [("shop/orders.py", "total = cart.subtotal()")],
    },
    # ------------------------------------------------------------------ db
    {
        "id": "db-missing-commit",
        "title": "Remove redundant commit",
        "edits": [("shop/db.py", "    cursor = connection.execute(query, params)\n    connection.commit()\n",
                   "    cursor = connection.execute(query, params)\n")],
        "bugs": [("shop/db.py", "    cursor = connection.execute(query, params)")],
    },
    {
        "id": "db-string-formatting",
        "title": "Simplify fetch_one",
        "edits": [("shop/db.py", "return connection.execute(query, params).fetchone()", "return connection.execute(query % params).fetchone()")],
        "bugs": [("shop/db.py", "return connection.execute(query % params).fetchone()")],
    },
    # ----------------------------------------------------------- new files
    {
        "id": "new-reports-module",
        "title": "Add report import and export",
        "edits": [("shop/reports.py", "",
                   '"""Import saved reports and export them as PDFs."""\n\n'
                   "import pickle\nimport subprocess\n\n\n"
                   "def load_report(uploaded_bytes: bytes) -> dict:\n"
                   "    return pickle.loads(uploaded_bytes)\n\n\n"
                   "def export_pdf(report_name: str) -> None:\n"
                   '    subprocess.run(f"wkhtmltopdf reports/{report_name}.html out/{report_name}.pdf", shell=True)\n')],
        "bugs": [("shop/reports.py", "return pickle.loads(uploaded_bytes)"), ("shop/reports.py", "shell=True)")],
    },
    {
        "id": "new-config-loader",
        "title": "Load shop settings from YAML",
        "edits": [("shop/config_loader.py", "",
                   '"""Reads shop settings from a YAML file."""\n\n'
                   "import yaml\n\n\n"
                   "def load_settings(path: str) -> dict:\n"
                   "    with open(path) as handle:\n"
                   "        return yaml.load(handle, Loader=yaml.Loader)\n")],
        "bugs": [("shop/config_loader.py", "return yaml.load(handle, Loader=yaml.Loader)")],
    },
    {
        "id": "new-admin-delete-user",
        "title": "Add admin endpoint to delete users",
        "edits": [("shop/admin.py", "",
                   '"""Admin-only operations."""\n\n'
                   "from shop import db\n\n\n"
                   "def delete_user(connection, token: str, user_id: int) -> None:\n"
                   '    db.execute(connection, "DELETE FROM users WHERE id = ?", (user_id,))\n')],
        "bugs": [("shop/admin.py", 'db.execute(connection, "DELETE FROM users')],
    },
    {
        "id": "new-notifications",
        "title": "Send order confirmation emails",
        "edits": [("shop/notifications.py", "",
                   '"""Sends transactional emails."""\n\n'
                   "import requests\n\n"
                   'EMAIL_API = "https://mail.example.com/send"\n\n\n'
                   "def send_email(to: str, subject: str, body: str, cc=[]) -> bool:\n"
                   '    cc.append("audit@tinyshop.in")\n'
                   '    response = requests.post(EMAIL_API, json={"to": to, "cc": cc, "subject": subject, "body": body})\n'
                   "    return response.status_code == 200\n")],
        "bugs": [("shop/notifications.py", "cc=[]) -> bool:"), ("shop/notifications.py", "response = requests.post(EMAIL_API")],
    },
]

CLEAN_CASES = [
    {
        "id": "clean-docstring",
        "title": "Document subtotal",
        "edits": [("shop/cart.py", "    def subtotal(self) -> int:\n",
                   '    def subtotal(self) -> int:\n        """Sum of price x quantity for every item, in paise."""\n')],
        "bugs": [],
    },
    {
        "id": "clean-rename",
        "title": "Rename loop variable in chunk",
        "edits": [("shop/utils.py", "return [items[index:index + size] for index in range(0, len(items), size)]",
                   "return [items[position:position + size] for position in range(0, len(items), size)]")],
        "bugs": [],
    },
    {
        "id": "clean-clamp",
        "title": "Add clamp helper",
        "edits": [("shop/utils.py", "def chunk(items: list, size: int) -> list:",
                   "def clamp(value: int, low: int, high: int) -> int:\n"
                   "    if low > high:\n        raise ValueError(\"low must not be greater than high\")\n"
                   "    return max(low, min(value, high))\n\n\n"
                   "def chunk(items: list, size: int) -> list:")],
        "bugs": [],
    },
    {
        "id": "clean-inventory-tests",
        "title": "Add inventory tests",
        "edits": [("tests/test_inventory.py", "",
                   "import pytest\n\nfrom shop import db, inventory\n\n\n"
                   "def make_connection():\n"
                   '    connection = db.connect(":memory:")\n'
                   "    db.create_schema(connection)\n"
                   '    db.execute(connection, "INSERT INTO products (name, price_paise, stock) VALUES (?, ?, ?)", ("Pen", 1000, 2))\n'
                   "    return connection\n\n\n"
                   "def test_reserve_reduces_stock():\n"
                   "    connection = make_connection()\n"
                   "    inventory.reserve_stock(connection, 1, 2)\n"
                   "    assert inventory.get_stock(connection, 1) == 0\n\n\n"
                   "def test_reserve_too_many_fails():\n"
                   "    connection = make_connection()\n"
                   "    with pytest.raises(inventory.OutOfStockError):\n"
                   "        inventory.reserve_stock(connection, 1, 3)\n")],
        "bugs": [],
    },
    {
        "id": "clean-cancel-logging",
        "title": "Log order cancellations",
        "edits": [("shop/orders.py",
                   '    db.execute(connection, "UPDATE orders SET status = ? WHERE id = ?", ("cancelled", order_id))\n    return True',
                   '    db.execute(connection, "UPDATE orders SET status = ? WHERE id = ?", ("cancelled", order_id))\n'
                   '    logger.info("Order %s cancelled by user %s", order_id, user_id)\n    return True')],
        "bugs": [],
    },
    {
        "id": "clean-count-products",
        "title": "Add product count",
        "edits": [("shop/inventory.py", "def search_products(",
                   "def count_products(connection) -> int:\n"
                   '    row = db.fetch_one(connection, "SELECT COUNT(*) AS total FROM products")\n'
                   '    return row["total"]\n\n\n'
                   "def search_products(")],
        "bugs": [],
    },
    {
        "id": "clean-cart-clear",
        "title": "Add Cart.clear",
        "edits": [("shop/cart.py", "    def item_count(self) -> int:",
                   "    def clear(self) -> None:\n        self.items = {}\n\n    def item_count(self) -> int:")],
        "bugs": [],
    },
    {
        "id": "clean-readme",
        "title": "Expand README",
        "edits": [("README.md", "Run the tests with `pytest`.",
                   "Run the tests with `pytest`.\n\n## Modules\n\n- `shop/cart.py` - shopping cart\n- `shop/orders.py` - checkout\n")],
        "bugs": [],
    },
    {
        "id": "clean-negative-rupees",
        "title": "Format negative amounts",
        "edits": [("shop/utils.py",
                   "    rupees = paise // 100\n    remainder = paise % 100\n    return f\"₹{rupees:,}.{remainder:02d}\"",
                   "    sign = \"-\" if paise < 0 else \"\"\n    paise = abs(paise)\n"
                   "    rupees = paise // 100\n    remainder = paise % 100\n    return f\"{sign}₹{rupees:,}.{remainder:02d}\"")],
        "bugs": [],
    },
    {
        "id": "clean-item-count-test",
        "title": "Test item_count",
        "edits": [("tests/test_cart.py", "def test_remove_item():",
                   "def test_item_count():\n    cart = Cart()\n    cart.add_item(1, 500, 3)\n    cart.add_item(2, 100)\n"
                   "    assert cart.item_count() == 4\n\n\ndef test_remove_item():")],
        "bugs": [],
    },
]

ALL_CASES = BUGGY_CASES + CLEAN_CASES
