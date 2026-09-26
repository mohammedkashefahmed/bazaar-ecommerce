"""API tests. Run from the project folder with:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        # Every test gets its own throwaway database file, pre-loaded with the demo data.
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.app = create_app({"DATABASE": self.db_path, "TESTING": True})
        self.client = self.app.test_client()

    def tearDown(self):
        os.remove(self.db_path)

    # -- helpers ---------------------------------------------------------------
    def register(self, email="asha@example.com", name="Asha", password="secret123"):
        res = self.client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
        return res

    def customer_headers(self, email="asha@example.com"):
        token = self.register(email).get_json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def admin_headers(self):
        res = self.client.post("/api/auth/login", json={"email": "admin@bazaar.test", "password": "admin123"})
        return {"Authorization": f"Bearer {res.get_json()['token']}"}

    def product_by_name(self, name):
        items = self.client.get("/api/products", query_string={"per_page": 100}).get_json()["items"]
        return next(p for p in items if p["name"] == name)

    def add_to_cart(self, headers, product_id, quantity=1):
        return self.client.post("/api/cart", json={"product_id": product_id, "quantity": quantity}, headers=headers)


class AuthTests(ApiTestCase):
    def test_register_returns_token_and_customer_role(self):
        res = self.register()
        self.assertEqual(res.status_code, 201)
        body = res.get_json()
        self.assertIn("token", body)
        self.assertEqual(body["user"]["role"], "customer")

    def test_register_rejects_duplicate_email(self):
        self.register()
        self.assertEqual(self.register().status_code, 409)

    def test_register_validates_input(self):
        self.assertEqual(self.register(email="not-an-email").status_code, 400)
        self.assertEqual(self.register(password="123").status_code, 400)
        self.assertEqual(self.register(name="  ").status_code, 400)

    def test_login_success_and_failure(self):
        self.register()
        ok = self.client.post("/api/auth/login", json={"email": "ASHA@example.com", "password": "secret123"})
        self.assertEqual(ok.status_code, 200)
        bad = self.client.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)

    def test_protected_route_needs_valid_token(self):
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        res = self.client.get("/api/me", headers={"Authorization": "Bearer not.a.token"})
        self.assertEqual(res.status_code, 401)
        res = self.client.get("/api/me", headers=self.customer_headers())
        self.assertEqual(res.get_json()["email"], "asha@example.com")


class ProductTests(ApiTestCase):
    def test_pagination(self):
        first = self.client.get("/api/products").get_json()
        self.assertEqual(first["total"], 14)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["items"]), 8)
        second = self.client.get("/api/products?page=2").get_json()
        self.assertEqual(len(second["items"]), 6)

    def test_search_and_category_filter(self):
        found = self.client.get("/api/products?q=keyboard").get_json()
        self.assertEqual([p["name"] for p in found["items"]], ["Mechanical Keyboard"])
        audio = self.client.get("/api/products?category=Audio").get_json()
        self.assertEqual(audio["total"], 3)

    def test_search_input_cannot_inject_sql(self):
        res = self.client.get("/api/products", query_string={"q": "'; DROP TABLE products; --"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get("/api/products").get_json()["total"], 14)

    def test_only_admin_can_manage_products(self):
        payload = {"name": "USB Cable", "category": "Desk", "price": 199, "stock": 10}
        self.assertEqual(self.client.post("/api/products", json=payload).status_code, 401)
        self.assertEqual(
            self.client.post("/api/products", json=payload, headers=self.customer_headers()).status_code, 403
        )
        created = self.client.post("/api/products", json=payload, headers=self.admin_headers())
        self.assertEqual(created.status_code, 201)

    def test_admin_can_update_and_delete_product(self):
        headers = self.admin_headers()
        pid = self.product_by_name("Sticky Notes")["id"]
        payload = {"name": "Sticky Notes XL", "category": "Stationery", "price": 179, "stock": 50}
        self.assertEqual(self.client.put(f"/api/products/{pid}", json=payload, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/products/{pid}").get_json()["price"], 179)
        self.assertEqual(self.client.delete(f"/api/products/{pid}", headers=headers).status_code, 204)
        self.assertEqual(self.client.get(f"/api/products/{pid}").status_code, 404)

    def test_product_validation(self):
        headers = self.admin_headers()
        bad = {"name": "Thing", "category": "Desk", "price": -5, "stock": 1}
        self.assertEqual(self.client.post("/api/products", json=bad, headers=headers).status_code, 400)


class CartAndOrderTests(ApiTestCase):
    def test_cart_add_update_remove(self):
        headers = self.customer_headers()
        pid = self.product_by_name("Gel Pen Pack")["id"]
        cart = self.add_to_cart(headers, pid, 2).get_json()
        self.assertEqual(cart["total"], 398)
        cart = self.add_to_cart(headers, pid, 1).get_json()
        self.assertEqual(cart["items"][0]["quantity"], 3)
        cart = self.client.put(f"/api/cart/{pid}", json={"quantity": 5}, headers=headers).get_json()
        self.assertEqual(cart["total"], 995)
        cart = self.client.delete(f"/api/cart/{pid}", headers=headers).get_json()
        self.assertEqual(cart["items"], [])

    def test_cannot_add_more_than_stock(self):
        headers = self.customer_headers()
        mug = self.product_by_name("Ceramic Coffee Mug")  # stock 3
        self.assertEqual(self.add_to_cart(headers, mug["id"], 4).status_code, 409)
        self.assertEqual(self.add_to_cart(headers, mug["id"], 3).status_code, 201)
        self.assertEqual(self.add_to_cart(headers, mug["id"], 1).status_code, 409)

    def test_cart_is_private_to_each_user(self):
        a = self.customer_headers("a@example.com")
        b = self.customer_headers("b@example.com")
        self.add_to_cart(a, self.product_by_name("Sticky Notes")["id"])
        self.assertEqual(self.client.get("/api/cart", headers=b).get_json()["items"], [])

    def test_checkout_creates_order_and_reduces_stock(self):
        headers = self.customer_headers()
        mouse = self.product_by_name("Wireless Mouse")
        self.add_to_cart(headers, mouse["id"], 2)
        res = self.client.post("/api/orders", json={"address": "12 MG Road, Karimnagar"}, headers=headers)
        self.assertEqual(res.status_code, 201)
        order = res.get_json()
        self.assertEqual(order["total"], 1598)
        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["items"][0]["quantity"], 2)
        self.assertEqual(self.product_by_name("Wireless Mouse")["stock"], mouse["stock"] - 2)
        self.assertEqual(self.client.get("/api/cart", headers=headers).get_json()["items"], [])
        self.assertEqual(len(self.client.get("/api/orders", headers=headers).get_json()), 1)

    def test_checkout_needs_items_and_address(self):
        headers = self.customer_headers()
        self.assertEqual(self.client.post("/api/orders", json={"address": "12 MG Road, Karimnagar"}, headers=headers).status_code, 400)
        self.add_to_cart(headers, self.product_by_name("Sticky Notes")["id"])
        self.assertEqual(self.client.post("/api/orders", json={"address": "short"}, headers=headers).status_code, 400)

    def test_checkout_rolls_back_when_stock_runs_out(self):
        first = self.customer_headers("first@example.com")
        second = self.customer_headers("second@example.com")
        mug = self.product_by_name("Ceramic Coffee Mug")  # stock 3
        pen = self.product_by_name("Gel Pen Pack")
        self.add_to_cart(second, pen["id"], 1)
        self.add_to_cart(second, mug["id"], 3)
        self.add_to_cart(first, mug["id"], 3)
        address = {"address": "12 MG Road, Karimnagar"}
        self.assertEqual(self.client.post("/api/orders", json=address, headers=first).status_code, 201)
        # The second shopper's cart still holds 3 mugs, but none are left.
        res = self.client.post("/api/orders", json=address, headers=second)
        self.assertEqual(res.status_code, 409)
        # Nothing was changed for them: pens not deducted, cart intact, no order created.
        self.assertEqual(self.product_by_name("Gel Pen Pack")["stock"], pen["stock"])
        self.assertEqual(len(self.client.get("/api/cart", headers=second).get_json()["items"]), 2)
        self.assertEqual(self.client.get("/api/orders", headers=second).get_json(), [])

    def test_admin_can_ship_and_cancel_order_and_stock_returns(self):
        customer = self.customer_headers()
        admin = self.admin_headers()
        bottle = self.product_by_name("Steel Water Bottle")
        self.add_to_cart(customer, bottle["id"], 4)
        order = self.client.post("/api/orders", json={"address": "12 MG Road, Karimnagar"}, headers=customer).get_json()
        self.assertEqual(self.product_by_name("Steel Water Bottle")["stock"], bottle["stock"] - 4)

        shipped = self.client.patch(f"/api/admin/orders/{order['id']}", json={"status": "shipped"}, headers=admin)
        self.assertEqual(shipped.get_json()["status"], "shipped")

        cancelled = self.client.patch(f"/api/admin/orders/{order['id']}", json={"status": "cancelled"}, headers=admin)
        self.assertEqual(cancelled.get_json()["status"], "cancelled")
        self.assertEqual(self.product_by_name("Steel Water Bottle")["stock"], bottle["stock"])
        again = self.client.patch(f"/api/admin/orders/{order['id']}", json={"status": "shipped"}, headers=admin)
        self.assertEqual(again.status_code, 409)

    def test_customer_cannot_use_admin_order_routes(self):
        headers = self.customer_headers()
        self.assertEqual(self.client.get("/api/admin/orders", headers=headers).status_code, 403)
        self.assertEqual(self.client.patch("/api/admin/orders/1", json={"status": "shipped"}, headers=headers).status_code, 403)

    def test_unknown_api_route_returns_json_404(self):
        res = self.client.get("/api/nope")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json(), {"error": "Not found"})


if __name__ == "__main__":
    unittest.main()
