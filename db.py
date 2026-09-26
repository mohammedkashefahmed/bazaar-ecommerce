"""SQLite connection handling, schema creation and demo data."""
import sqlite3
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# (name, category, price in rupees, stock, emoji, description)
SEED_PRODUCTS = [
    ("Wireless Earbuds", "Audio", 1999, 25, "🎧", "Bluetooth 5.3 earbuds with a charging case and 20 hours of playback."),
    ("Bluetooth Speaker", "Audio", 2499, 12, "🔊", "Water-resistant pocket speaker with deep bass."),
    ("Wired Headphones", "Audio", 899, 30, "🎵", "Over-ear headphones with a 3.5 mm cable and in-line mic."),
    ("LED Desk Lamp", "Desk", 1299, 18, "💡", "Dimmable lamp with three colour temperatures and a USB port."),
    ("Laptop Stand", "Desk", 1499, 9, "💻", "Foldable aluminium stand that lifts your screen to eye level."),
    ("Mechanical Keyboard", "Desk", 3499, 6, "⌨️", "Compact 75% layout with hot-swappable switches."),
    ("Wireless Mouse", "Desk", 799, 40, "🖱️", "Quiet-click mouse with an 18-month battery."),
    ("Ruled Notebook Set", "Stationery", 349, 60, "📓", "Pack of three A5 notebooks, 200 pages each."),
    ("Gel Pen Pack", "Stationery", 199, 100, "🖊️", "Ten smooth 0.5 mm gel pens in assorted colours."),
    ("Sticky Notes", "Stationery", 149, 80, "🗒️", "Six pads of bright sticky notes."),
    ("Steel Water Bottle", "Kitchen", 599, 35, "🧴", "Insulated 750 ml bottle that keeps drinks cold for 24 hours."),
    ("Ceramic Coffee Mug", "Kitchen", 299, 3, "☕", "Hand-glazed 350 ml mug, dishwasher safe."),
    ("Lunch Box", "Kitchen", 499, 22, "🍱", "Leak-proof, three-compartment lunch box."),
    ("Coffee Press", "Kitchen", 1199, 0, "🫖", "Glass French press that brews four cups."),
]


def get_db():
    """Return the SQLite connection for the current request (created on first use)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app):
    """Create tables and, on a brand-new database, add a demo admin and products."""
    with app.app_context():
        conn = get_db()
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        seed(conn)
        conn.commit()


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("Store Admin", "admin@bazaar.test", generate_password_hash("admin123")),
        )
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO products (name, category, price, stock, emoji, description) VALUES (?, ?, ?, ?, ?, ?)",
            SEED_PRODUCTS,
        )
