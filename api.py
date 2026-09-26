"""All REST endpoints for Bazaar, grouped as: auth, products, cart, orders, admin."""
import re
import sqlite3

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth import admin_required, create_token, login_required
from db import get_db
from helpers import error, get_json, is_int

bp = Blueprint("api", __name__, url_prefix="/api")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ORDER_STATUSES = ("placed", "shipped", "delivered", "cancelled")
PAGE_SIZE = 8


class OutOfStock(Exception):
    """Raised inside checkout when a product no longer has enough stock."""


def public_user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}


# --------------------------------------------------------------------------- auth

@bp.post("/auth/register")
def register():
    data = get_json()
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name:
        return error("Enter your name")
    if not EMAIL_RE.match(email):
        return error("Enter a valid email address")
    if len(password) < 6:
        return error("Password must be at least 6 characters")

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        db.commit()
    except sqlite3.IntegrityError:  # the UNIQUE constraint on users.email
        return error("That email is already registered", 409)

    user = {"id": cur.lastrowid, "name": name, "email": email, "role": "customer"}
    return jsonify({"token": create_token(user["id"], user["role"]), "user": user}), 201


@bp.post("/auth/login")
def login():
    data = get_json()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    # Same message for "no such user" and "wrong password" so attackers can't probe for accounts.
    if row is None or not check_password_hash(row["password_hash"], password):
        return error("Incorrect email or password", 401)
    return jsonify({"token": create_token(row["id"], row["role"]), "user": public_user(row)})


@bp.get("/me")
@login_required
def me():
    return jsonify(public_user(g.user))


# ----------------------------------------------------------------------- products

def parse_product(data):
    """Validate a product payload. Returns (fields, None) or (None, error message)."""
    fields = {
        "name": str(data.get("name", "")).strip(),
        "category": str(data.get("category", "")).strip(),
        "description": str(data.get("description", "")).strip(),
        "emoji": str(data.get("emoji", "")).strip() or "📦",
        "price": data.get("price"),
        "stock": data.get("stock"),
    }
    if not fields["name"]:
        return None, "Product name is required"
    if not fields["category"]:
        return None, "Category is required"
    if not is_int(fields["price"]) or fields["price"] < 0:
        return None, "Price must be a whole number of rupees (0 or more)"
    if not is_int(fields["stock"]) or fields["stock"] < 0:
        return None, "Stock must be a whole number (0 or more)"
    return fields, None


@bp.get("/products")
def list_products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = min(max(request.args.get("per_page", PAGE_SIZE, type=int), 1), 100)

    # Only fixed SQL fragments are joined into the query; user input always goes through "?" params.
    conditions, params = [], []
    if q:
        conditions.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if category:
        conditions.append("category = ?")
        params.append(category)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM products {where}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT * FROM products {where} ORDER BY id LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page],
    ).fetchall()
    return jsonify({
        "items": [dict(r) for r in rows],
        "page": page,
        "pages": max(1, -(-total // per_page)),  # ceiling division
        "total": total,
    })


@bp.get("/categories")
def list_categories():
    rows = get_db().execute("SELECT DISTINCT category FROM products ORDER BY category").fetchall()
    return jsonify([r["category"] for r in rows])


@bp.get("/products/<int:product_id>")
def get_product(product_id):
    row = get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        return error("Product not found", 404)
    return jsonify(dict(row))


@bp.post("/products")
@admin_required
def create_product():
    fields, problem = parse_product(get_json())
    if problem:
        return error(problem)
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (name, category, description, emoji, price, stock) "
        "VALUES (:name, :category, :description, :emoji, :price, :stock)",
        fields,
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, **fields}), 201


@bp.put("/products/<int:product_id>")
@admin_required
def update_product(product_id):
    fields, problem = parse_product(get_json())
    if problem:
        return error(problem)
    db = get_db()
    cur = db.execute(
        "UPDATE products SET name = :name, category = :category, description = :description, "
        "emoji = :emoji, price = :price, stock = :stock WHERE id = :id",
        {**fields, "id": product_id},
    )
    db.commit()
    if cur.rowcount == 0:
        return error("Product not found", 404)
    return jsonify({"id": product_id, **fields})


@bp.delete("/products/<int:product_id>")
@admin_required
def delete_product(product_id):
    db = get_db()
    cur = db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    if cur.rowcount == 0:
        return error("Product not found", 404)
    return "", 204


# --------------------------------------------------------------------------- cart

def cart_payload(db, user_id):
    rows = db.execute(
        "SELECT c.product_id, c.quantity, p.name, p.price, p.stock, p.emoji "
        "FROM cart_items c JOIN products p ON p.id = c.product_id "
        "WHERE c.user_id = ? ORDER BY c.rowid",
        (user_id,),
    ).fetchall()
    items = [dict(r) for r in rows]
    return {"items": items, "total": sum(i["price"] * i["quantity"] for i in items)}


@bp.get("/cart")
@login_required
def get_cart():
    return jsonify(cart_payload(get_db(), g.user["id"]))


@bp.post("/cart")
@login_required
def add_to_cart():
    data = get_json()
    product_id = data.get("product_id")
    quantity = data.get("quantity", 1)
    if not is_int(product_id) or not is_int(quantity) or quantity < 1:
        return error("A product and a quantity of at least 1 are required")

    db = get_db()
    product = db.execute("SELECT id, stock FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return error("Product not found", 404)

    existing = db.execute(
        "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
        (g.user["id"], product_id),
    ).fetchone()
    wanted = quantity + (existing["quantity"] if existing else 0)
    if wanted > product["stock"]:
        return error(f"Only {product['stock']} in stock", 409)

    db.execute(
        "INSERT INTO cart_items (user_id, product_id, quantity) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id, product_id) DO UPDATE SET quantity = quantity + excluded.quantity",
        (g.user["id"], product_id, quantity),
    )
    db.commit()
    return jsonify(cart_payload(db, g.user["id"])), 201


@bp.put("/cart/<int:product_id>")
@login_required
def set_cart_quantity(product_id):
    quantity = get_json().get("quantity")
    if not is_int(quantity) or quantity < 1:
        return error("Quantity must be at least 1")

    db = get_db()
    product = db.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        return error("Product not found", 404)
    if quantity > product["stock"]:
        return error(f"Only {product['stock']} in stock", 409)

    cur = db.execute(
        "UPDATE cart_items SET quantity = ? WHERE user_id = ? AND product_id = ?",
        (quantity, g.user["id"], product_id),
    )
    db.commit()
    if cur.rowcount == 0:
        return error("That product is not in your cart", 404)
    return jsonify(cart_payload(db, g.user["id"]))


@bp.delete("/cart/<int:product_id>")
@login_required
def remove_from_cart(product_id):
    db = get_db()
    db.execute("DELETE FROM cart_items WHERE user_id = ? AND product_id = ?", (g.user["id"], product_id))
    db.commit()
    return jsonify(cart_payload(db, g.user["id"]))


# ------------------------------------------------------------------------- orders

def fetch_order(db, order_id):
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return attach_items(db, [order])[0] if order else None


def attach_items(db, order_rows):
    """Turn order rows into dicts and add each order's line items (one extra query per order)."""
    orders = []
    for row in order_rows:
        order = dict(row)
        order["items"] = [
            dict(i)
            for i in db.execute(
                "SELECT product_id, product_name, unit_price, quantity FROM order_items WHERE order_id = ?",
                (row["id"],),
            )
        ]
        orders.append(order)
    return orders


@bp.post("/orders")
@login_required
def place_order():
    """Checkout: turn the cart into an order.

    Stock is reduced with 'UPDATE ... WHERE stock >= qty'. That single statement checks and
    decrements atomically, so two shoppers can never buy the last item. Everything happens in
    one transaction: if any line is short, we roll back and no stock is touched.
    """
    address = str(get_json().get("address", "")).strip()
    if len(address) < 10:
        return error("Enter a delivery address (at least 10 characters)")

    db = get_db()
    cart = cart_payload(db, g.user["id"])
    if not cart["items"]:
        return error("Your cart is empty")

    try:
        for item in cart["items"]:
            cur = db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (item["quantity"], item["product_id"], item["quantity"]),
            )
            if cur.rowcount == 0:
                raise OutOfStock(item["name"])

        cur = db.execute(
            "INSERT INTO orders (user_id, total, address) VALUES (?, ?, ?)",
            (g.user["id"], cart["total"], address),
        )
        order_id = cur.lastrowid
        db.executemany(
            "INSERT INTO order_items (order_id, product_id, product_name, unit_price, quantity) "
            "VALUES (?, ?, ?, ?, ?)",
            [(order_id, i["product_id"], i["name"], i["price"], i["quantity"]) for i in cart["items"]],
        )
        db.execute("DELETE FROM cart_items WHERE user_id = ?", (g.user["id"],))
        db.commit()
    except OutOfStock as exc:
        db.rollback()
        return error(f"Not enough stock for {exc}", 409)
    except Exception:
        db.rollback()
        raise

    return jsonify(fetch_order(db, order_id)), 201


@bp.get("/orders")
@login_required
def my_orders():
    db = get_db()
    rows = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (g.user["id"],)).fetchall()
    return jsonify(attach_items(db, rows))


# ------------------------------------------------------------------------- admin

@bp.get("/admin/orders")
@admin_required
def all_orders():
    db = get_db()
    rows = db.execute(
        "SELECT o.*, u.name AS customer_name, u.email AS customer_email "
        "FROM orders o JOIN users u ON u.id = o.user_id ORDER BY o.id DESC"
    ).fetchall()
    return jsonify(attach_items(db, rows))


@bp.patch("/admin/orders/<int:order_id>")
@admin_required
def update_order_status(order_id):
    status = get_json().get("status")
    if status not in ORDER_STATUSES:
        return error("Status must be one of: " + ", ".join(ORDER_STATUSES))

    db = get_db()
    order = fetch_order(db, order_id)
    if order is None:
        return error("Order not found", 404)
    if order["status"] == "cancelled":
        return error("A cancelled order cannot be changed", 409)

    if status == "cancelled":  # put the stock back
        for item in order["items"]:
            if item["product_id"] is not None:
                db.execute(
                    "UPDATE products SET stock = stock + ? WHERE id = ?",
                    (item["quantity"], item["product_id"]),
                )
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    db.commit()
    return jsonify(fetch_order(db, order_id))
