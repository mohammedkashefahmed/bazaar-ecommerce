# Bazaar: Full-Stack E-Commerce App

A small online store with a REST API, JWT login, a shopping cart, checkout and an admin panel.

**Stack:** Python 3 · Flask · SQLite · JWT (PyJWT) · vanilla JavaScript, HTML, CSS

## Features

- Register and sign in. Passwords are hashed, and sessions use signed JWT tokens
- Two roles: **customer** and **admin**, enforced on the server
- Product catalogue with search, category filter and pagination
- Server-side cart that follows the user across devices
- Checkout that runs in one database transaction, so stock can never go negative
- Order history for customers
- Admin panel: add, edit and delete products; view all orders; change order status (cancelling an order returns its stock)
- 20 automated API tests

## Run it (about 5 minutes)

You need Python 3.9 or newer. Check with `python --version` (on Windows try `py --version`).

**Windows (Command Prompt or PowerShell)**

```
cd bazaar
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**macOS / Linux**

```
cd bazaar
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

The first start creates `bazaar.db` with 14 demo products and an admin account:

| Role | Email | Password |
|---|---|---|
| Admin | admin@bazaar.test | admin123 |
| Customer | create one with "Sign in" then "Create an account" | (your choice) |

To reset everything, stop the server, delete `bazaar.db` and start again.

## Run the tests

```
python -m unittest discover -s tests -v
```

No extra installs needed. Each test uses its own temporary database.

## Project structure

```
bazaar/
├── app.py          Creates the Flask app, registers routes, serves the page
├── api.py          Every REST endpoint (auth, products, cart, orders, admin)
├── auth.py         JWT creation and the login_required / admin_required decorators
├── db.py           SQLite connection, schema loading, demo data
├── helpers.py      JSON error helper and small validators
├── schema.sql      All tables and constraints
├── static/
│   ├── index.html  Page shell
│   ├── style.css   Styling
│   └── app.js      Frontend logic (calls the API with fetch)
├── tests/test_api.py
├── requirements.txt
└── Dockerfile      Optional
```

## API reference

Send the token as `Authorization: Bearer <token>`. Errors always look like `{"error": "message"}`.

| Method | Path | Who | What it does |
|---|---|---|---|
| POST | `/api/auth/register` | anyone | Create a customer account, returns a token |
| POST | `/api/auth/login` | anyone | Returns a token |
| GET | `/api/me` | signed in | Current user |
| GET | `/api/products?q=&category=&page=` | anyone | Search, filter, paginate |
| GET | `/api/categories` | anyone | List of categories |
| GET | `/api/products/<id>` | anyone | One product |
| POST / PUT / DELETE | `/api/products[/<id>]` | admin | Create, update, delete a product |
| GET | `/api/cart` | signed in | Your cart with total |
| POST | `/api/cart` | signed in | Add `{product_id, quantity}` |
| PUT / DELETE | `/api/cart/<product_id>` | signed in | Set quantity or remove |
| POST | `/api/orders` | signed in | Checkout with `{address}` |
| GET | `/api/orders` | signed in | Your orders |
| GET | `/api/admin/orders` | admin | All orders |
| PATCH | `/api/admin/orders/<id>` | admin | Set `status` |

## How the important parts work (read this before an interview)

1. **Login.** `auth/login` checks the password against a hash (`check_password_hash`) and returns a JWT that expires after 12 hours. The browser stores it and sends it on every request. `login_required` in `auth.py` verifies the signature and loads the user.
2. **Roles.** `admin_required` wraps `login_required` and returns 403 unless `role == 'admin'`. The check is on the server, so hiding the Admin button in the browser is only cosmetic.
3. **Checkout.** `place_order` in `api.py` runs `UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?` for each cart line. That one statement checks and reduces stock together. If any line fails, the whole transaction is rolled back. Order lines copy the product name and price, so old orders stay correct if a product changes later.
4. **SQL injection.** Every query uses `?` placeholders. There is a test that sends `'; DROP TABLE products; --` as a search.
5. **XSS.** The frontend escapes all product and user text with `esc()` before putting it in the page.

## Make it yours (do at least two of these)

Adding your own features is what turns this from a download into your project.

- **Easy:** product reviews and ratings, a wishlist, sort by price, a "low stock" filter in admin
- **Medium:** real product image uploads, order confirmation email (Flask-Mail), password reset, coupon codes
- **Harder:** payments in test mode (Razorpay or Stripe sandbox), move from SQLite to PostgreSQL, add rate limiting on login, switch the backend to Java Spring Boot

Write a test for every feature you add.

## Optional: Docker

```
docker build -t bazaar .
docker run -p 8000:8000 -e SECRET_KEY=change-me-to-a-long-random-string bazaar
```

Then open http://127.0.0.1:8000. The Dockerfile was not run while this project was being prepared, so if it fails on your machine, the normal Python steps above are the reliable route.

## Before you deploy anywhere public

- Set a long random `SECRET_KEY` environment variable
- Remove or change the demo admin account in `db.py`
- Use a production server such as gunicorn instead of `python app.py`
