"use strict";

/* ============================================================================
   Bazaar frontend: plain JavaScript, no build step.
   Flow: user clicks -> `actions` / `forms` call the REST API -> we re-render.
   ========================================================================== */

// ---------------------------------------------------------------- app state
const state = {
  token: localStorage.getItem("token"),
  user: null,
  view: "shop",            // "shop" | "orders" | "admin"
  q: "",
  category: "",
  page: 1,
  cart: { items: [], total: 0 },
  address: "",             // kept here so re-rendering the cart doesn't erase what you typed
  authMode: "login",       // "login" | "register"
  editing: null,           // product being edited in the admin form
  productId: null,         // which product "product" view is showing
  draftRating: 0,          // star picker value while writing a review
};
let adminProducts = [];
let renderId = 0;

// ------------------------------------------------------------------ helpers
const $ = (selector) => document.querySelector(selector);
const rupees = (n) => "₹" + Number(n).toLocaleString("en-IN");
const hue = (text) => [...text].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
const firstName = (name) => name.split(" ")[0];

// Escape text before putting it into HTML. This stops a product named "<script>..."
// from running code in someone's browser (XSS).
const esc = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const formatDate = (sqlTimestamp) =>
  new Date(sqlTimestamp.replace(" ", "T") + "Z").toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

// Renders a static (non-interactive) star row, e.g. ★★★★☆. Rounds to the nearest whole star.
function starRow(rating) {
  const filled = Math.round(rating || 0);
  return "★".repeat(filled) + "☆".repeat(5 - filled);
}

function ratingSummary(p) {
  if (!p.review_count) return `<span class="stars muted">No reviews yet</span>`;
  return `<span class="stars" aria-label="${p.avg_rating} out of 5 stars">${starRow(p.avg_rating)}</span> ${p.avg_rating} (${p.review_count})`;
}

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 3200);
}

// One wrapper for every server call: adds the JWT, parses JSON, turns errors into exceptions.
async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = "Bearer " + state.token;

  const res = await fetch("/api" + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = res.status === 204 ? {} : await res.json().catch(() => ({}));

  if (!res.ok) {
    if (res.status === 401 && state.token) logout(false); // token expired or invalid
    throw new Error(data.error || "Something went wrong. Try again");
  }
  return data;
}

// -------------------------------------------------------------- session
function renderHeader() {
  const signedIn = Boolean(state.user);
  $("#nav-orders").hidden = !signedIn;
  $("#nav-admin").hidden = !(signedIn && state.user.role === "admin");
  $("#nav-auth").textContent = signedIn ? `Sign out (${firstName(state.user.name)})` : "Sign in";
}

function logout(notify = true) {
  state.token = null;
  state.user = null;
  state.cart = { items: [], total: 0 };
  state.editing = null;
  localStorage.removeItem("token");
  toggleCart(false);
  renderHeader();
  renderCart();
  render();
  if (notify) toast("Signed out");
}

async function loadCart() {
  state.cart = await api("/cart");
  renderCart();
}

// ------------------------------------------------------------ cart drawer
function toggleCart(open) {
  $("#cart").classList.toggle("open", open);
  $("#cart").inert = !open;
  $("#scrim").classList.toggle("open", open);
}

function renderCart() {
  $("#cart-count").textContent = state.cart.items.reduce((n, i) => n + i.quantity, 0);
  const body = $("#cart-body");

  if (!state.cart.items.length) {
    body.innerHTML = `<p class="empty">Your cart is empty.<br>Add something from the shop.</p>`;
    return;
  }

  const lines = state.cart.items
    .map(
      (i) => `
      <div class="line-item">
        <div class="line-emoji" aria-hidden="true">${esc(i.emoji)}</div>
        <div>
          <div class="line-name">${esc(i.name)}</div>
          <div class="line-sub">${rupees(i.price)} each</div>
          <div class="qty">
            <button data-action="qty" data-id="${i.product_id}" data-delta="-1" aria-label="One fewer ${esc(i.name)}">−</button>
            <span>${i.quantity}</span>
            <button data-action="qty" data-id="${i.product_id}" data-delta="1" aria-label="One more ${esc(i.name)}">+</button>
          </div>
        </div>
        <div>
          <strong>${rupees(i.price * i.quantity)}</strong><br>
          <button class="link" data-action="remove" data-id="${i.product_id}">Remove</button>
        </div>
      </div>`
    )
    .join("");

  body.innerHTML = `
    ${lines}
    <div class="cart-total"><span>Total</span><span>${rupees(state.cart.total)}</span></div>
    <form data-form="checkout">
      <label>Delivery address
        <textarea name="address" required minlength="10" placeholder="House number, street, city, PIN code">${esc(state.address)}</textarea>
      </label>
      <button class="btn primary block" type="submit">Place order</button>
    </form>`;
}

// ---------------------------------------------------------- sign-in dialog
function openAuth(mode = "login", message = "") {
  state.authMode = mode;
  renderAuth(message);
  $("#auth").showModal();
}

function renderAuth(message = "") {
  const register = state.authMode === "register";
  $("#auth").innerHTML = `
    <form data-form="auth">
      <h2 id="auth-title">${register ? "Create your account" : "Sign in"}</h2>
      ${message ? `<p class="hint">${esc(message)}</p>` : ""}
      ${register ? `<label>Name<input name="name" required autocomplete="name"></label>` : ""}
      <label>Email<input name="email" type="email" required autocomplete="email"></label>
      <label>Password
        <input name="password" type="password" required minlength="6" autocomplete="${register ? "new-password" : "current-password"}">
      </label>
      <p class="form-error" id="auth-error" role="alert"></p>
      <button class="btn primary block" type="submit">${register ? "Create account" : "Sign in"}</button>
      <div class="dialog-actions">
        <button type="button" class="link" data-action="auth-mode" data-value="${register ? "login" : "register"}">
          ${register ? "I already have an account" : "Create an account"}
        </button>
        <button type="button" class="link" data-action="close-auth">Cancel</button>
      </div>
      ${register ? "" : `<p class="hint">Demo admin account: admin@bazaar.test / admin123</p>`}
    </form>`;
}

// ------------------------------------------------------------------- views
// Each view function fetches its data and returns an HTML string. render() puts it on the page.

function productCard(p) {
  const out = p.stock === 0;
  const note = out
    ? `<span class="stock out">Sold out</span>`
    : p.stock <= 5
    ? `<span class="stock low">Only ${p.stock} left</span>`
    : `<span class="stock">In stock</span>`;
  return `
    <article class="card">
      <div class="tile" style="--h:${hue(p.category)}" aria-hidden="true">${esc(p.emoji)}</div>
      <div class="card-body">
        <span class="card-cat">${esc(p.category)}</span>
        <button class="card-title link-reset" data-action="open-product" data-id="${p.id}">${esc(p.name)}</button>
        <p class="card-rating">${ratingSummary(p)}</p>
        <p class="card-desc">${esc(p.description)}</p>
        <div class="card-foot">
          <div><div class="price">${rupees(p.price)}</div>${note}</div>
          <button class="btn primary" data-action="add" data-id="${p.id}" ${out ? "disabled" : ""}>Add to cart</button>
        </div>
      </div>
    </article>`;
}

function pager(d) {
  return `
    <div class="pager">
      <button class="btn small" data-action="page" data-value="${d.page - 1}" ${d.page <= 1 ? "disabled" : ""}>Previous</button>
      <span>Page ${d.page} of ${d.pages}</span>
      <button class="btn small" data-action="page" data-value="${d.page + 1}" ${d.page >= d.pages ? "disabled" : ""}>Next</button>
    </div>`;
}

async function shopView() {
  const params = new URLSearchParams({ page: state.page });
  if (state.q) params.set("q", state.q);
  if (state.category) params.set("category", state.category);

  const [categories, data] = await Promise.all([api("/categories"), api(`/products?${params}`)]);
  if (!data.items.length && state.page > 1) {
    state.page = 1;
    return shopView();
  }

  const tabs = ["", ...categories]
    .map(
      (c) =>
        `<button class="tab" data-action="category" data-value="${esc(c)}" aria-pressed="${state.category === c}">${c ? esc(c) : "All"}</button>`
    )
    .join("");
  const heading = state.q ? `Results for “${esc(state.q)}”` : "Everyday things for work and home";

  return `
    <div class="page-head">
      <h1>${heading}</h1>
      <p>${data.total} product${data.total === 1 ? "" : "s"}</p>
    </div>
    <div class="tabs" role="group" aria-label="Categories">${tabs}</div>
    ${
      data.items.length
        ? `<div class="grid">${data.items.map(productCard).join("")}</div>`
        : `<p class="empty">Nothing matches your search. Try another word or pick a different category.</p>`
    }
    ${data.pages > 1 ? pager(data) : ""}`;
}

function orderCard(o, admin) {
  const lines = o.items
    .map((i) => `<li><span>${esc(i.product_name)} × ${i.quantity}</span><span>${rupees(i.unit_price * i.quantity)}</span></li>`)
    .join("");
  const statusSelect = `
    <select data-order-status="${o.id}" aria-label="Status of order ${o.id}" ${o.status === "cancelled" ? "disabled" : ""}>
      ${["placed", "shipped", "delivered", "cancelled"]
        .map((s) => `<option value="${s}" ${s === o.status ? "selected" : ""}>${s}</option>`)
        .join("")}
    </select>`;
  return `
    <article class="order">
      <div class="order-head">
        <h2>Order #${o.id}</h2>
        <span class="status ${o.status}">${o.status}</span>
      </div>
      <div class="order-meta">
        ${formatDate(o.created_at)}<br>
        ${admin ? `Customer: ${esc(o.customer_name)}, ${esc(o.customer_email)}<br>` : ""}
        Deliver to: ${esc(o.address)}
      </div>
      <ul class="order-lines">${lines}</ul>
      <div class="order-foot">
        <strong>Total ${rupees(o.total)}</strong>
        ${admin ? statusSelect : ""}
      </div>
    </article>`;
}

async function ordersView() {
  const orders = await api("/orders");
  return `
    <div class="page-head"><h1>My orders</h1></div>
    ${orders.length ? orders.map((o) => orderCard(o, false)).join("") : `<p class="empty">You haven't placed an order yet.</p>`}`;
}

async function adminView() {
  const [products, orders] = await Promise.all([api("/products?per_page=100"), api("/admin/orders")]);
  adminProducts = products.items;
  const p = state.editing || { name: "", category: "", price: "", stock: "", emoji: "", description: "" };
  const categories = [...new Set(adminProducts.map((x) => x.category))];

  const rows = adminProducts
    .map(
      (x) => `
      <tr>
        <td>${esc(x.emoji)} ${esc(x.name)}</td>
        <td>${esc(x.category)}</td>
        <td>${rupees(x.price)}</td>
        <td>${x.stock}</td>
        <td class="actions">
          <button class="btn small" data-action="edit" data-id="${x.id}">Edit</button>
          <button class="btn small danger" data-action="delete" data-id="${x.id}">Delete</button>
        </td>
      </tr>`
    )
    .join("");

  return `
    <div class="page-head"><h1>Admin</h1><p>Manage products and orders.</p></div>

    <section class="section">
      <h2>${state.editing ? "Edit product" : "Add a product"}</h2>
      <form class="panel" data-form="product">
        <div class="form-grid">
          <label>Name<input name="name" required value="${esc(p.name)}"></label>
          <label>Category<input name="category" required list="category-list" value="${esc(p.category)}"></label>
          <label>Price (₹)<input name="price" type="number" min="0" step="1" required value="${esc(p.price)}"></label>
          <label>Stock<input name="stock" type="number" min="0" step="1" required value="${esc(p.stock)}"></label>
          <label>Emoji<input name="emoji" maxlength="8" placeholder="📦" value="${esc(p.emoji)}"></label>
          <label class="wide">Description<textarea name="description">${esc(p.description)}</textarea></label>
        </div>
        <datalist id="category-list">${categories.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
        <button class="btn primary" type="submit">${state.editing ? "Save changes" : "Add product"}</button>
        ${state.editing ? `<button class="btn" type="button" data-action="cancel-edit">Cancel</button>` : ""}
      </form>
    </section>

    <section class="section">
      <h2>Products</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Product</th><th>Category</th><th>Price</th><th>Stock</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>

    <section class="section">
      <h2>Orders</h2>
      ${orders.length ? orders.map((o) => orderCard(o, true)).join("") : `<p class="empty">No orders yet.</p>`}
    </section>`;
}

function reviewCard(r, productId) {
  const mine = state.user && r.user_id === state.user.id;
  return `
    <article class="review">
      <div class="review-head">
        <strong>${esc(r.reviewer_name)}${mine ? " (you)" : ""}</strong>
        <span class="stars" aria-label="${r.rating} out of 5 stars">${starRow(r.rating)}</span>
      </div>
      <p class="review-date">${formatDate(r.created_at)}</p>
      ${r.comment ? `<p>${esc(r.comment)}</p>` : ""}
      ${mine ? `<button class="link" data-action="delete-review" data-id="${productId}">Delete your review</button>` : ""}
    </article>`;
}

function starPicker() {
  const buttons = [1, 2, 3, 4, 5]
    .map(
      (n) =>
        `<button type="button" class="star-btn" data-action="rate" data-value="${n}" aria-label="${n} star${n > 1 ? "s" : ""}"
           aria-pressed="${state.draftRating >= n}">${state.draftRating >= n ? "★" : "☆"}</button>`
    )
    .join("");
  return `<div class="star-picker" role="group" aria-label="Your rating">${buttons}</div>`;
}

async function productView(id) {
  const [product, reviews] = await Promise.all([api(`/products/${id}`), api(`/products/${id}/reviews`)]);
  const mine = state.user ? reviews.find((r) => r.user_id === state.user.id) : null;
  const out = product.stock === 0;

  let reviewSection;
  if (!state.user) {
    reviewSection = `<p class="hint">Sign in to write a review.</p>`;
  } else if (mine) {
    reviewSection = `<p class="hint">You already reviewed this product. Delete your review below to write a new one.</p>`;
  } else {
    reviewSection = `
      <form data-form="review" class="panel">
        <input type="hidden" name="product_id" value="${id}">
        ${starPicker()}
        <label>Comment (optional)<textarea name="comment" maxlength="500" placeholder="What did you think?"></textarea></label>
        <button class="btn primary" type="submit" ${state.draftRating ? "" : "disabled"}>Submit review</button>
      </form>`;
  }

  return `
    <button class="link" data-action="nav" data-view="shop">&larr; Back to shop</button>
    <div class="product-detail">
      <div class="tile large" style="--h:${hue(product.category)}" aria-hidden="true">${esc(product.emoji)}</div>
      <div>
        <span class="card-cat">${esc(product.category)}</span>
        <h1>${esc(product.name)}</h1>
        <p class="card-rating">${ratingSummary(product)}</p>
        <p>${esc(product.description)}</p>
        <div class="card-foot">
          <div><div class="price">${rupees(product.price)}</div>
            <span class="stock ${out ? "out" : product.stock <= 5 ? "low" : ""}">${out ? "Sold out" : product.stock <= 5 ? `Only ${product.stock} left` : "In stock"}</span>
          </div>
          <button class="btn primary" data-action="add" data-id="${product.id}" ${out ? "disabled" : ""}>Add to cart</button>
        </div>
      </div>
    </div>

    <section class="section">
      <h2>Reviews${reviews.length ? ` (${reviews.length})` : ""}</h2>
      ${reviewSection}
      ${reviews.length ? reviews.map((r) => reviewCard(r, id)).join("") : `<p class="empty">No reviews yet — be the first.</p>`}
    </section>`;
}

async function render() {
  const id = ++renderId; // if a newer render starts while we wait for the server, drop this one
  let html;
  try {
    if (state.view === "product" && state.productId) html = await productView(state.productId);
    else if (state.view === "orders" && state.user) html = await ordersView();
    else if (state.view === "admin" && state.user && state.user.role === "admin") html = await adminView();
    else {
      state.view = "shop";
      html = await shopView();
    }
  } catch (err) {
    html = `<p class="empty">${esc(err.message)}</p>`;
  }
  if (id !== renderId) return;
  $("#view").innerHTML = html;
  document
    .querySelectorAll(".nav-link[data-view]")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === state.view));
}

// ----------------------------------------------------------------- clicks
// One listener for the whole page. Any element with data-action="name" runs actions[name].
const actions = {
  nav({ view }) {
    state.view = view;
    toggleCart(false);
    render();
  },
  category({ value }) {
    state.category = value;
    state.page = 1;
    render();
  },
  page({ value }) {
    state.page = Number(value);
    render();
    window.scrollTo({ top: 0 });
  },
  async add({ id }) {
    if (!state.user) return openAuth("login", "Sign in to add items to your cart.");
    try {
      state.cart = await api("/cart", { method: "POST", body: { product_id: Number(id), quantity: 1 } });
      renderCart();
      toast("Added to cart");
    } catch (err) {
      toast(err.message, true);
    }
  },
  async qty({ id, delta }) {
    const item = state.cart.items.find((i) => i.product_id === Number(id));
    if (!item) return;
    const quantity = item.quantity + Number(delta);
    try {
      state.cart =
        quantity < 1
          ? await api(`/cart/${id}`, { method: "DELETE" })
          : await api(`/cart/${id}`, { method: "PUT", body: { quantity } });
      renderCart();
    } catch (err) {
      toast(err.message, true);
    }
  },
  async remove({ id }) {
    try {
      state.cart = await api(`/cart/${id}`, { method: "DELETE" });
      renderCart();
    } catch (err) {
      toast(err.message, true);
    }
  },
  cart() {
    if (!state.user) return openAuth("login", "Sign in to see your cart.");
    toggleCart(true);
  },
  "open-product"({ id }) {
    state.productId = Number(id);
    state.draftRating = 0;
    state.view = "product";
    render();
    window.scrollTo({ top: 0 });
  },
  rate({ value }) {
    // Update the stars and the submit button in place. A full render() here would re-fetch the
    // product and reviews from the server and replace the form, wiping out any comment already typed.
    state.draftRating = Number(value);
    document.querySelectorAll(".star-btn").forEach((btn) => {
      const n = Number(btn.dataset.value);
      const on = state.draftRating >= n;
      btn.textContent = on ? "★" : "☆";
      btn.setAttribute("aria-pressed", on);
    });
    const submit = document.querySelector('[data-form="review"] button[type="submit"]');
    if (submit) submit.disabled = false;
  },
  async "delete-review"({ id }) {
    if (!confirm("Delete your review?")) return;
    try {
      await api(`/products/${id}/reviews/mine`, { method: "DELETE" });
      toast("Review deleted");
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
  "close-cart": () => toggleCart(false),
  auth() {
    if (state.user) logout();
    else openAuth();
  },
  "auth-mode"({ value }) {
    state.authMode = value;
    renderAuth();
  },
  "close-auth": () => $("#auth").close(),
  edit({ id }) {
    state.editing = adminProducts.find((p) => p.id === Number(id)) || null;
    render();
    window.scrollTo({ top: 0 });
  },
  "cancel-edit"() {
    state.editing = null;
    render();
  },
  async delete({ id }) {
    if (!confirm("Delete this product? Past orders keep their record of it.")) return;
    try {
      await api(`/products/${id}`, { method: "DELETE" });
      toast("Product deleted");
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
};

document.addEventListener("click", (event) => {
  const el = event.target.closest("[data-action]");
  if (el && actions[el.dataset.action]) actions[el.dataset.action](el.dataset);
});

// ------------------------------------------------------------------ forms
const forms = {
  async auth(_form, data) {
    const register = state.authMode === "register";
    const body = { email: data.get("email"), password: data.get("password") };
    if (register) body.name = data.get("name");
    try {
      const res = await api(register ? "/auth/register" : "/auth/login", { method: "POST", body });
      state.token = res.token;
      state.user = res.user;
      localStorage.setItem("token", res.token);
      $("#auth").close();
      renderHeader();
      await loadCart();
      toast(`Welcome, ${firstName(res.user.name)}`);
      render();
    } catch (err) {
      $("#auth-error").textContent = err.message;
    }
  },

  async checkout() {
    try {
      await api("/orders", { method: "POST", body: { address: state.address.trim() } });
      state.address = "";
      await loadCart();
      toggleCart(false);
      state.view = "orders";
      render();
      toast("Order placed. Thank you!");
    } catch (err) {
      toast(err.message, true);
      loadCart().catch(() => {});
    }
  },

  async review(_form, data) {
    const productId = data.get("product_id");
    try {
      await api(`/products/${productId}/reviews`, {
        method: "POST",
        body: { rating: state.draftRating, comment: data.get("comment") },
      });
      state.draftRating = 0;
      toast("Review posted");
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },

  async product(_form, data) {
    const body = {
      name: data.get("name"),
      category: data.get("category"),
      emoji: data.get("emoji"),
      description: data.get("description"),
      price: Number(data.get("price")),
      stock: Number(data.get("stock")),
    };
    const editing = state.editing;
    try {
      if (editing) await api(`/products/${editing.id}`, { method: "PUT", body });
      else await api("/products", { method: "POST", body });
      state.editing = null;
      toast(editing ? "Product saved" : "Product added");
      render();
    } catch (err) {
      toast(err.message, true);
    }
  },
};

document.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-form]");
  if (!form || !forms[form.dataset.form]) return;
  event.preventDefault();
  await forms[form.dataset.form](form, new FormData(form));
});

// Remember the delivery address while typing (see state.address above).
document.addEventListener("input", (event) => {
  if (event.target.name === "address") state.address = event.target.value;
});

// Admin: changing an order's status dropdown saves immediately.
document.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-order-status]");
  if (!select) return;
  try {
    await api(`/admin/orders/${select.dataset.orderStatus}`, { method: "PATCH", body: { status: select.value } });
    toast("Order updated");
  } catch (err) {
    toast(err.message, true);
  }
  render();
});

// Search box: wait 300 ms after the last keystroke so we don't call the server on every letter.
let searchTimer;
$("#search").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = event.target.value.trim();
    state.page = 1;
    state.view = "shop";
    render();
  }, 300);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") toggleCart(false);
});

// ------------------------------------------------------------------ start
async function init() {
  if (state.token) {
    try {
      state.user = await api("/me");
      await loadCart();
    } catch (_err) {
      /* the token was invalid or expired; api() already signed us out */
    }
  }
  renderHeader();
  renderCart();
  render();
}

init();
