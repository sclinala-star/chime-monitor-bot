import os
import sqlite3
from datetime import datetime
from config import DATABASE_PATH

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _use_postgres():
    return bool(DATABASE_URL)


def get_connection():
    if _use_postgres():
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetchone_dict(cursor):
    if _use_postgres():
        row = cursor.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cursor.description]
        return dict(zip(cols, row))
    row = cursor.fetchone()
    return dict(row) if row else None


def _fetchall_dict(cursor):
    if _use_postgres():
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, r)) for r in rows]
    rows = cursor.fetchall()
    return [dict(r) for r in rows]


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    if _use_postgres():
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                tag TEXT NOT NULL,
                amount REAL NOT NULL,
                sender TEXT NOT NULL,
                previous_total REAL NOT NULL,
                new_total REAL NOT NULL,
                previous_balance REAL NOT NULL,
                new_balance REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                tag TEXT PRIMARY KEY,
                total REAL NOT NULL DEFAULT 0.0,
                balance REAL NOT NULL DEFAULT 0.0
            )
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT NOT NULL,
                amount REAL NOT NULL,
                sender TEXT NOT NULL,
                previous_total REAL NOT NULL,
                new_total REAL NOT NULL,
                previous_balance REAL NOT NULL,
                new_balance REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                tag TEXT PRIMARY KEY,
                total REAL NOT NULL DEFAULT 0.0,
                balance REAL NOT NULL DEFAULT 0.0
            )
        """)
    conn.commit()
    conn.close()


def get_account(tag: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    if _use_postgres():
        cursor.execute("SELECT * FROM accounts WHERE tag = %s", (tag,))
    else:
        cursor.execute("SELECT * FROM accounts WHERE tag = ?", (tag,))
    row = _fetchone_dict(cursor)
    conn.close()
    if row:
        return {"tag": row["tag"], "total": row["total"], "balance": row["balance"]}
    return {"tag": tag, "total": 0.0, "balance": 0.0}


def set_account(tag: str, total: float, balance: float):
    conn = get_connection()
    cursor = conn.cursor()
    if _use_postgres():
        cursor.execute(
            "INSERT INTO accounts (tag, total, balance) VALUES (%s, %s, %s) "
            "ON CONFLICT(tag) DO UPDATE SET total = %s, balance = %s",
            (tag, total, balance, total, balance),
        )
    else:
        cursor.execute(
            "INSERT INTO accounts (tag, total, balance) VALUES (?, ?, ?) "
            "ON CONFLICT(tag) DO UPDATE SET total = ?, balance = ?",
            (tag, total, balance, total, balance),
        )
    conn.commit()
    conn.close()


def add_payment(tag: str, amount: float, sender: str) -> dict:
    account = get_account(tag)
    previous_total = account["total"]
    new_total = round(previous_total + amount, 2)
    previous_balance = account["balance"]
    new_balance = round(previous_balance + amount, 2)
    now = datetime.now().isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    if _use_postgres():
        cursor.execute(
            "INSERT INTO payments (tag, amount, sender, previous_total, new_total, "
            "previous_balance, new_balance, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (tag, amount, sender, previous_total, new_total, previous_balance, new_balance, now),
        )
    else:
        cursor.execute(
            "INSERT INTO payments (tag, amount, sender, previous_total, new_total, "
            "previous_balance, new_balance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tag, amount, sender, previous_total, new_total, previous_balance, new_balance, now),
        )
    conn.commit()
    conn.close()

    set_account(tag, new_total, new_balance)

    return {
        "tag": tag,
        "amount": amount,
        "sender": sender,
        "previous_total": previous_total,
        "new_total": new_total,
        "previous_balance": previous_balance,
        "new_balance": new_balance,
    }


def set_balance(tag: str, balance: float):
    account = get_account(tag)
    set_account(tag, account["total"], balance)


def set_total(tag: str, total: float):
    account = get_account(tag)
    set_account(tag, total, account["balance"])


def get_recent_payments(tag: str, limit: int = 10) -> list:
    conn = get_connection()
    cursor = conn.cursor()
    if _use_postgres():
        cursor.execute(
            "SELECT * FROM payments WHERE tag = %s ORDER BY id DESC LIMIT %s",
            (tag, limit),
        )
    else:
        cursor.execute(
            "SELECT * FROM payments WHERE tag = ? ORDER BY id DESC LIMIT ?",
            (tag, limit),
        )
    rows = _fetchall_dict(cursor)
    conn.close()
    return rows
