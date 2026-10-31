import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("SECRETS_FILE", "/nonexistent/github_app.json")

SAMPLE_DIFF = """diff --git a/app/auth.py b/app/auth.py
index 1111111..2222222 100644
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,6 +1,9 @@
 import sqlite3


-def find_user(db, name):
-    return db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
+def find_user(db, name):
+    query = f"SELECT * FROM users WHERE name = '{name}'"
+    return db.execute(query).fetchone()
+
+
+API_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


 def login(db, name, password):
"""

SAMPLE_NEW_FILE = """import sqlite3


def find_user(db, name):
    query = f"SELECT * FROM users WHERE name = '{name}'"
    return db.execute(query).fetchone()


API_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def login(db, name, password):
    user = find_user(db, name)
    return user is not None and user[2] == password
"""
