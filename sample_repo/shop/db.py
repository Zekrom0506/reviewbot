"""Database helpers. All SQL in the project must go through this module."""

import sqlite3

DATABASE_PATH = "shop.db"


def connect(path: str = DATABASE_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def fetch_one(connection: sqlite3.Connection, query: str, params: tuple = ()):
    return connection.execute(query, params).fetchone()


def fetch_all(connection: sqlite3.Connection, query: str, params: tuple = ()) -> list:
    return connection.execute(query, params).fetchall()


def execute(connection: sqlite3.Connection, query: str, params: tuple = ()) -> int:
    cursor = connection.execute(query, params)
    connection.commit()
    return cursor.lastrowid


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price_paise INTEGER NOT NULL,
            stock INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            total_paise INTEGER NOT NULL,
            status TEXT NOT NULL
        );
        """
    )
