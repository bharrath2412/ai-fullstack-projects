/**
 * BillBook admin — hand-written ES modules, no framework, no build step.
 *
 * The whole client is: a token in sessionStorage, one `api()` helper that adds
 * the bearer header, and a router over location.hash. Every view is a function
 * that renders HTML into #view and then wires its own events, so there is no
 * hidden state machine to reason about.
 */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const state = {
  token: sessionStorage.getItem('bb.token'),
  user: null,
  tenant: null,
  meta: null,
  items: [],
  invoiceDraft: [],
};

const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (char) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
  ));

const inr = (value) =>
  '₹' + Number(value ?? 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const qty = (value) => Number(value ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 3 });

function toast(message, kind = 'ok') {
  const node = $('#toast');
  node.textContent = message;
  node.className = `toast ${kind}`;
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 3600);
}

async function api(path, { method = 'GET', body, raw = false } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (raw) return response;
  const type = response.headers.get('content-type') || '';
  const payload = type.includes('json') ? await response.json().catch(() => null) : null;
  if (response.status === 401 && state.token) {
    signOut('Session expired — please sign in again.');
    throw new Error('Session expired');
  }
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  return payload;
}

function signOut(message) {
  state.token = null;
  state.user = null;
  state.tenant = null;
  sessionStorage.removeItem('bb.token');
  $('#topbar').hidden = true;
  if (message) toast(message, 'error');
  location.hash = '#/login';
  route();
}

function setChrome() {
  const authed = Boolean(state.token && state.user);
  $('#topbar').hidden = !authed;
  if (!authed) return;
  $('#tenant-name').textContent = state.tenant?.name || 'BillBook';
  $('#tenant-meta').textContent = `GSTIN ${state.tenant?.gstin || 'unregistered'} · state ${state.tenant?.state_code}`;
  $('#role-pill').textContent = `${state.user.name || state.user.email} · ${state.user.role}`;
  $('#payment-pill').textContent = state.meta?.payments?.mode || 'razorpay-simulated';
  try {
    sessionStorage.setItem('bb.tenant', JSON.stringify(state.tenant));
  } catch { /* storage full or blocked: the header still works for this page view */ }
  const current = (location.hash.replace('#/', '') || 'dashboard').split('/')[0];
  $$('[data-nav]').forEach((link) => {
    if (link.dataset.nav === current) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('#version').textContent = state.meta?.version || '1.0.0';
}

// --------------------------------------------------------------------------- //
// auth
// --------------------------------------------------------------------------- //
function viewLogin(mode = 'login') {
  const isRegister = mode === 'register';
  $('#view').innerHTML = `
    <div class="auth-wrap">
      <div class="card">
        <h1>${isRegister ? 'Create your shop' : 'Sign in to BillBook'}</h1>
        <p class="muted">${isRegister
          ? 'One tenant, one owner, unlimited invoices. GST-compliant from the first bill.'
          : 'GST invoicing, stock that updates itself, and reports your accountant will accept.'}</p>
        <div class="auth-tabs" role="tablist">
          <button role="tab" aria-selected="${!isRegister}" data-mode="login">Sign in</button>
          <button role="tab" aria-selected="${isRegister}" data-mode="register">Register</button>
        </div>
        <form id="auth-form">
          ${isRegister ? `
            <label class="field"><span>Shop / business name</span>
              <input name="tenant_name" required minlength="2" placeholder="Chennai Gadgets" /></label>
            <label class="field"><span>GST state code (2 digits)</span>
              <input name="state_code" required pattern="\\d{2}" value="33" /></label>
            <label class="field"><span>GSTIN (optional)</span>
              <input name="gstin" placeholder="33AABCU9603R1ZM" /></label>
            <label class="field"><span>Your name</span>
              <input name="name" required placeholder="Owner" /></label>
          ` : ''}
          <label class="field"><span>Email</span>
            <input name="email" type="email" required autocomplete="username" placeholder="you@shop.in" /></label>
          <label class="field"><span>Password</span>
            <input name="password" type="password" required minlength="8"
                   autocomplete="${isRegister ? 'new-password' : 'current-password'}" placeholder="at least 8 characters" /></label>
          <button class="btn primary" type="submit">${isRegister ? 'Create shop' : 'Sign in'}</button>
        </form>
        ${isRegister ? '' : `<p class="hintbox" style="margin-top:1rem">New here? Register creates a tenant and an
          owner account. Demo data can be loaded with <code>python -m scripts.seed</code>.</p>`}
      </div>
    </div>`;

  $$('.auth-tabs button').forEach((button) => {
    button.addEventListener('click', () => viewLogin(button.dataset.mode));
  });

  $('#auth-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.target).entries());
    const submit = $('button[type=submit]', event.target);
    submit.disabled = true;
    try {
      const path = isRegister ? '/api/auth/register' : '/api/auth/login';
      const body = isRegister
        ? { ...data, gstin: data.gstin || null, address: null }
        : { email: data.email, password: data.password };
      const result = await api(path, { method: 'POST', body });
      state.token = result.access_token;
      state.user = result.user;
      state.tenant = result.tenant;
      sessionStorage.setItem('bb.token', result.access_token);
      setChrome();
      toast(isRegister ? 'Shop created — welcome aboard.' : `Signed in as ${result.user.role}.`);
      location.hash = '#/dashboard';
      route();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  });
}

// --------------------------------------------------------------------------- //
// dashboard
// --------------------------------------------------------------------------- //
async function viewDashboard() {
  const [summary, health] = await Promise.all([
    api('/api/reports/summary?days=30').catch(() => null),
    fetch('/health').then((r) => r.json()),
  ]);

  if (!summary) {
    $('#view').innerHTML = `<div class="card"><h2>Reports are restricted</h2>
      <p class="muted">Your role (${esc(state.user.role)}) can bill customers but not read the
      financial reports. Ask the owner for an accountant login.</p></div>`;
    return;
  }

  const lowStock = summary.low_stock || [];
  $('#view').innerHTML = `
    <h1>Last 30 days</h1>
    <p class="muted">${summary.invoice_count} invoices issued · ${summary.cancelled_count} cancelled ·
      ${health.db?.items ?? 0} items in the catalogue</p>

    <div class="grid cols-4" style="margin-bottom:1rem">
      ${stat('Gross sales', inr(summary.gross_sales), 'incl. GST')}
      ${stat('Tax collected', inr(summary.tax_collected), `cess ${inr(summary.cess_collected)}`)}
      ${stat('Paid', inr(summary.paid_amount), 'captured payments')}
      ${stat('Outstanding', inr(summary.outstanding_amount), 'issued, unpaid')}
    </div>

    <div class="split">
      <div class="card">
        <div class="card-head"><h2>Daily sales</h2><span class="pill">${summary.daily.length} days</span></div>
        ${summary.daily.length ? `
          <div class="table-wrap"><table>
            <thead><tr><th>Date</th><th class="num">Invoices</th><th class="num">Total</th></tr></thead>
            <tbody>${[...summary.daily].reverse().map((row) => `
              <tr><td>${esc(row.date)}</td><td class="num">${row.invoices}</td>
                  <td class="num">${inr(row.total)}</td></tr>`).join('')}</tbody>
          </table></div>` : '<p class="empty">No invoices yet — create one from the Invoices tab.</p>'}
      </div>

      <div class="card">
        <div class="card-head"><h2>Top items</h2></div>
        ${summary.top_items.length ? `<div class="table-wrap"><table>
          <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Revenue</th></tr></thead>
          <tbody>${summary.top_items.map((row) => `<tr>
            <td>${esc(row.description)}${row.sku ? `<br><small class="muted">${esc(row.sku)}</small>` : ''}</td>
            <td class="num">${qty(row.qty)}</td><td class="num">${inr(row.revenue)}</td></tr>`).join('')}
          </tbody></table></div>` : '<p class="empty">Nothing sold yet.</p>'}
        <div class="card-head" style="margin-top:1rem">
          <h3>Low stock</h3><span class="pill">${lowStock.length}</span>
        </div>
        ${lowStock.length ? `<ul style="margin:0;padding-left:1.1rem">${lowStock.map((item) => `
          <li>${esc(item.name)} — ${qty(item.stock_qty)} ${esc(item.unit)} left
          <span class="tag low">reorder at ${qty(item.reorder_level)}</span></li>`).join('')}</ul>`
          : '<p class="muted">Everything is above its reorder level.</p>'}
      </div>
    </div>

    <div class="card">
      <div class="card-head"><h2>Runtime</h2><span class="pill">measured, this process</span></div>
      <div class="grid cols-4">
        ${stat('p50 latency', `${health.latency_ms.p50} ms`, `${health.latency_ms.samples} samples`)}
        ${stat('p95 latency', `${health.latency_ms.p95} ms`, `max ${health.latency_ms.max} ms`)}
        ${stat('Database', health.db.ok ? 'ok' : 'degraded', `${health.db.invoices} invoices`)}
        ${stat('Payments', health.payments.mode, health.payments.live_keys ? 'real test keys' : 'simulated locally')}
      </div>
    </div>`;
}

const stat = (label, value, hint) => `
  <div class="stat"><div class="label">${esc(label)}</div>
  <div class="value">${value}</div><div class="hint">${esc(hint)}</div></div>`;

// --------------------------------------------------------------------------- //
// items
// --------------------------------------------------------------------------- //
async function viewItems() {
  const [items, meta] = await Promise.all([
    api('/api/items'),
    state.meta ? Promise.resolve(state.meta) : api('/api/meta').catch(() => null),
  ]);
  const canEdit = state.user.role === 'owner';
  const canAdjust = ['owner', 'staff'].includes(state.user.role);

  $('#view').innerHTML = `
    <h1>Items</h1>
    <p class="muted">Unit prices exclude GST. Stock decrements when an invoice is issued and comes
      back if it is cancelled.</p>

    <div class="card">
      <div class="card-head">
        <h2>Catalogue <span class="pill">${items.length}</span></h2>
        <input id="item-search" placeholder="Search name, SKU or HSN" style="max-width:260px" />
      </div>
      <div class="table-wrap">
        <table id="items-table">
          <thead><tr>
            <th>SKU</th><th>Item</th><th>HSN</th><th class="num">Price</th><th class="num">GST</th>
            <th class="num">Stock</th><th>${canAdjust ? 'Adjust' : ''}</th>
          </tr></thead>
          <tbody>${items.length ? items.map(itemRow).join('')
            : '<tr><td class="empty" colspan="7">No items yet.</td></tr>'}</tbody>
        </table>
      </div>
    </div>

    ${canEdit ? `
    <div class="card">
      <h2>Add an item</h2>
      <form id="item-form" class="row">
        <label class="field"><span>SKU</span><input name="sku" required placeholder="WM-01" /></label>
        <label class="field"><span>Name</span><input name="name" required placeholder="Wireless mouse" /></label>
        <label class="field"><span>HSN</span><input name="hsn" placeholder="8471" /></label>
        <label class="field"><span>Unit price (₹, excl. GST)</span>
          <input name="unit_price" type="number" step="0.01" min="0.01" required value="599" /></label>
        <label class="field"><span>GST rate</span>
          <select name="gst_rate">${(meta?.gst_rates || [0, 5, 12, 18, 28])
            .map((rate) => `<option value="${rate}" ${rate === 18 ? 'selected' : ''}>${rate}%</option>`).join('')}</select></label>
        <label class="field"><span>Opening stock</span>
          <input name="stock_qty" type="number" step="0.001" min="0" value="0" /></label>
        <label class="field"><span>Reorder level</span>
          <input name="reorder_level" type="number" step="0.001" min="0" value="5" /></label>
        <div style="flex:0 0 auto"><button class="btn primary" type="submit">Add item</button></div>
      </form>
    </div>` : ''}`;

  const search = $('#item-search');
  search.addEventListener('input', () => {
    const needle = search.value.trim().toLowerCase();
    $$('#items-table tbody tr').forEach((row) => {
      row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
    });
  });

  $$('[data-adjust]').forEach((button) => {
    button.addEventListener('click', async () => {
      const itemId = button.dataset.adjust;
      const raw = prompt('Quantity change (e.g. 12 for receipt, -3 for damage):', '10');
      if (!raw) return;
      try {
        await api(`/api/items/${itemId}/stock`, {
          method: 'POST',
          body: { delta: Number(raw), reason: 'manual adjustment from admin' },
        });
        toast('Stock updated.');
        viewItems();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  });

  const form = $('#item-form');
  if (form) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      try {
        await api('/api/items', {
          method: 'POST',
          body: {
            sku: data.sku,
            name: data.name,
            hsn: data.hsn || null,
            unit: 'pcs',
            unit_price: Number(data.unit_price),
            gst_rate: Number(data.gst_rate),
            stock_qty: Number(data.stock_qty || 0),
            reorder_level: Number(data.reorder_level || 0),
          },
        });
        toast(`${data.name} added.`);
        viewItems();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  }
}

const itemRow = (item) => `
  <tr>
    <td class="mono">${esc(item.sku)}</td>
    <td>${esc(item.name)}${item.low_stock ? ' <span class="tag low">low</span>' : ''}
      ${item.active ? '' : ' <span class="tag cancelled">inactive</span>'}</td>
    <td class="mono">${esc(item.hsn || '—')}</td>
    <td class="num">${inr(item.unit_price)}</td>
    <td class="num">${item.gst_rate}%</td>
    <td class="num">${qty(item.stock_qty)} ${esc(item.unit)}</td>
    <td>${['owner', 'staff'].includes(state.user.role)
      ? `<button class="btn small" data-adjust="${item.id}">Adjust</button>` : ''}</td>
  </tr>`;

// --------------------------------------------------------------------------- //
// invoices
// --------------------------------------------------------------------------- //
async function viewInvoices() {
  const [invoices, items] = await Promise.all([api('/api/invoices'), api('/api/items')]);
  state.items = items;
  const canBill = ['owner', 'staff'].includes(state.user.role);

  $('#view').innerHTML = `
    <h1>Invoices</h1>
    <p class="muted">Numbers are allocated per financial year: <code>INV/2026-27/0001</code>.</p>

    ${canBill ? invoiceComposer(items) : `<div class="card"><p class="muted">Your role
      (${esc(state.user.role)}) can view and download invoices but not issue them.</p></div>`}

    <div class="card">
      <div class="card-head"><h2>All invoices <span class="pill">${invoices.length}</span></h2></div>
      <div class="table-wrap"><table>
        <thead><tr><th>Number</th><th>Customer</th><th>Status</th><th class="num">Total</th>
          <th>Issued</th><th></th></tr></thead>
        <tbody>${invoices.length ? invoices.map((invoice) => `
          <tr>
            <td class="mono">${esc(invoice.number)}</td>
            <td>${esc(invoice.customer_name)}
              <br><small class="muted">${invoice.supply_type === 'intra' ? 'CGST+SGST' : 'IGST'} · POS ${esc(invoice.place_of_supply)}</small></td>
            <td><span class="tag ${invoice.status}">${invoice.status}</span></td>
            <td class="num">${inr(invoice.total)}</td>
            <td><small>${esc(invoice.issued_at.replace('T', ' ').slice(0, 16))}</small></td>
            <td><a class="btn small" href="#/invoice/${invoice.id}">Open</a></td>
          </tr>`).join('') : '<tr><td class="empty" colspan="6">No invoices yet.</td></tr>'}
        </tbody>
      </table></div>
    </div>`;

  if (canBill) wireComposer();
}

function invoiceComposer(items) {
  return `
    <div class="card">
      <div class="card-head">
        <h2>New invoice</h2>
        <span class="pill">${items.length} items in catalogue</span>
      </div>
      <form id="invoice-form">
        <div class="row">
          <label class="field"><span>Customer name</span>
            <input name="customer_name" required placeholder="Sri Traders" /></label>
          <label class="field"><span>Customer GSTIN (optional, makes it B2B)</span>
            <input name="customer_gstin" placeholder="33ABCDE1234F1Z5" /></label>
          <label class="field"><span>Place of supply</span>
            <input name="place_of_supply" value="${esc(state.tenant.state_code)}" pattern="\\d{2}"
                   title="2-digit GST state code. Different from your state → IGST." /></label>
        </div>
        <div class="table-wrap">
          <table class="line-editor">
            <thead><tr><th>Item</th><th class="num">Qty</th><th class="num">Unit price</th>
              <th class="num">Disc %</th><th class="num">GST %</th><th></th></tr></thead>
            <tbody id="lines"></tbody>
          </table>
        </div>
        <div class="row tight" style="margin:0.6rem 0">
          <button class="btn small" type="button" id="add-line">+ Add line</button>
          <button class="btn small" type="button" id="add-custom">+ Custom line</button>
          <span class="muted" id="live-total" style="flex:1;text-align:right"></span>
        </div>
        <label class="field"><span>Notes (printed on the invoice)</span>
          <input name="notes" placeholder="Delivered by 20 Nov" /></label>
        <button class="btn primary" type="submit">Issue invoice</button>
      </form>
    </div>`;
}

function lineRow(item, index) {
  const options = state.items.map((candidate) => `
    <option value="${candidate.id}" ${item && candidate.id === item.id ? 'selected' : ''}>
      ${esc(candidate.name)} — ${inr(candidate.unit_price)} @ ${candidate.gst_rate}%
    </option>`).join('');
  return `
    <tr data-line="${index}">
      <td><select class="line-item"><option value="">Custom line…</option>${options}</select></td>
      <td class="num"><input class="line-qty" type="number" min="0.001" step="0.001" value="1" /></td>
      <td class="num"><input class="line-price" type="number" min="0.01" step="0.01" placeholder="auto" /></td>
      <td class="num"><input class="line-disc" type="number" min="0" max="100" step="0.01" value="0" /></td>
      <td class="num"><input class="line-rate" type="number" min="0" step="1" placeholder="auto" /></td>
      <td><button type="button" class="btn small danger" data-remove>×</button></td>
    </tr>`;
}

function wireComposer() {
  const form = $('#invoice-form');
  const lines = $('#lines');
  let index = 0;

  const addLine = () => {
    lines.insertAdjacentHTML('beforeend', lineRow(null, index++));
    lines.lastElementChild.querySelector('.line-item').focus();
    updateTotal();
  };

  const readLines = () => $$('tr[data-line]', lines).map((row) => {
    const itemId = row.querySelector('.line-item').value;
    const item = state.items.find((candidate) => String(candidate.id) === itemId);
    const price = row.querySelector('.line-price').value;
    const rate = row.querySelector('.line-rate').value;
    return {
      item_id: item ? item.id : null,
      description: item ? item.name : 'Custom line',
      qty: Number(row.querySelector('.line-qty').value || 0),
      unit_price: price ? Number(price) : (item ? item.unit_price : null),
      discount_pct: Number(row.querySelector('.line-disc').value || 0),
      gst_rate: rate ? Number(rate) : (item ? item.gst_rate : 18),
    };
  }).filter((line) => line.qty > 0 && line.unit_price);

  const updateTotal = () => {
    const draft = readLines();
    const gross = draft.reduce((sum, line) => {
      const taxable = line.qty * line.unit_price * (1 - line.discount_pct / 100);
      return sum + taxable * (1 + line.gst_rate / 100);
    }, 0);
    $('#live-total').textContent = draft.length
      ? `${draft.length} line(s) · approx ${inr(Math.round(gross))} (round-off applied on issue)`
      : 'Add at least one line';
  };

  lines.addEventListener('input', updateTotal);
  lines.addEventListener('change', (event) => {
    const row = event.target.closest('tr[data-line]');
    if (!row) return;
    if (event.target.classList.contains('line-item')) {
      const item = state.items.find((candidate) => String(candidate.id) === event.target.value);
      if (item) {
        row.querySelector('.line-price').value = item.unit_price;
        row.querySelector('.line-rate').value = item.gst_rate;
      }
    }
    updateTotal();
  });
  lines.addEventListener('click', (event) => {
    if (event.target.dataset.remove !== undefined) {
      event.target.closest('tr').remove();
      updateTotal();
    }
  });

  $('#add-line').addEventListener('click', addLine);
  $('#add-custom').addEventListener('click', addLine);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    const draft = readLines();
    if (!draft.length) {
      toast('Add at least one line with a quantity and price.', 'error');
      return;
    }
    const submit = $('button[type=submit]', form);
    submit.disabled = true;
    try {
      const invoice = await api('/api/invoices', {
        method: 'POST',
        body: {
          customer_name: data.customer_name,
          customer_gstin: data.customer_gstin || null,
          place_of_supply: data.place_of_supply || null,
          notes: data.notes || null,
          lines: draft,
        },
      });
      toast(`${invoice.number} issued — ${inr(invoice.total)}.`);
      location.hash = `#/invoice/${invoice.id}`;
      route();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      submit.disabled = false;
    }
  });

  addLine();
}

async function viewInvoice(id) {
  const invoice = await api(`/api/invoices/${id}`);
  const canCancel = state.user.role === 'owner' && invoice.status === 'issued';
  const canPay = ['owner', 'staff'].includes(state.user.role) && invoice.status === 'issued';

  $('#view').innerHTML = `
    <div class="card">
      <div class="card-head">
        <div>
          <h1>${esc(invoice.number)}</h1>
          <p class="muted">${esc(invoice.customer_name)} ·
            POS ${esc(invoice.place_of_supply)} ·
            ${invoice.supply_type === 'intra' ? 'CGST + SGST' : 'IGST'} ·
            <span class="tag ${invoice.status}">${invoice.status}</span></p>
        </div>
        <div class="row tight">
          <button class="btn" id="download-pdf">Download PDF</button>
          ${canPay ? '<button class="btn primary" id="pay">Pay (test mode)</button>' : ''}
          ${canCancel ? '<button class="btn danger" id="cancel">Cancel invoice</button>' : ''}
        </div>
      </div>

      <div class="table-wrap"><table>
        <thead><tr><th>Description</th><th>HSN</th><th class="num">Qty</th><th class="num">Rate</th>
          <th class="num">Disc%</th><th class="num">Taxable</th><th class="num">GST%</th>
          <th class="num">CGST</th><th class="num">SGST</th><th class="num">IGST</th>
          <th class="num">Total</th></tr></thead>
        <tbody>${invoice.lines.map((line) => `
          <tr>
            <td>${esc(line.description)}</td>
            <td class="mono">${esc(line.hsn || '—')}</td>
            <td class="num">${qty(line.qty)}</td>
            <td class="num">${inr(line.unit_price)}</td>
            <td class="num">${line.discount_pct}</td>
            <td class="num">${inr(line.taxable_value)}</td>
            <td class="num">${line.gst_rate}</td>
            <td class="num">${inr(line.cgst)}</td>
            <td class="num">${inr(line.sgst)}</td>
            <td class="num">${inr(line.igst)}</td>
            <td class="num">${inr(line.line_total)}</td>
          </tr>`).join('')}</tbody>
      </table></div>

      <div class="totals" style="margin-top:0.9rem">
        <span>Taxable value</span><span class="num">${inr(invoice.subtotal)}</span>
        ${invoice.discount_total ? `<span>Discount</span><span class="num">−${inr(invoice.discount_total)}</span>` : ''}
        ${invoice.cgst ? `<span>CGST</span><span class="num">${inr(invoice.cgst)}</span>` : ''}
        ${invoice.sgst ? `<span>SGST</span><span class="num">${inr(invoice.sgst)}</span>` : ''}
        ${invoice.igst ? `<span>IGST</span><span class="num">${inr(invoice.igst)}</span>` : ''}
        ${invoice.cess ? `<span>Cess</span><span class="num">${inr(invoice.cess)}</span>` : ''}
        <span>Round off</span><span class="num">${inr(invoice.round_off)}</span>
        <span class="grand">Total</span><span class="grand num">${inr(invoice.total)}</span>
      </div>
      <p class="words">${esc(invoice.amount_in_words)}</p>
    </div>

    <div class="split">
      <div class="card">
        <h2>Tax summary</h2>
        <div class="table-wrap"><table>
          <thead><tr><th class="num">Rate</th><th class="num">Taxable</th><th class="num">CGST</th>
            <th class="num">SGST</th><th class="num">IGST</th><th class="num">Total</th></tr></thead>
          <tbody>${(invoice.lines.length ? groupByRate(invoice.lines) : []).map((row) => `
            <tr><td class="num">${row.gst_rate}%</td><td class="num">${inr(row.taxable_value)}</td>
              <td class="num">${inr(row.cgst)}</td><td class="num">${inr(row.sgst)}</td>
              <td class="num">${inr(row.igst)}</td><td class="num">${inr(row.line_total)}</td></tr>`).join('')}
          </tbody></table></div>
      </div>

      <div class="card">
        <h2>Payments</h2>
        ${invoice.payments && invoice.payments.length ? `<ul style="margin:0;padding-left:1.1rem">
          ${invoice.payments.map((payment) => `<li><code>${esc(payment.order_id)}</code> ·
            ${inr(payment.amount)} · ${payment.status}
            ${payment.signature_verified ? '· signature verified' : ''}</li>`).join('')}
          </ul>` : '<p class="muted">No payment attempts yet. Test mode: no money moves.</p>'}
        <p class="muted" style="margin-top:0.75rem">Issued
          ${esc(invoice.issued_at.replace('T', ' ').slice(0, 16))}
          ${invoice.paid_at ? ` · paid ${esc(invoice.paid_at.replace('T', ' ').slice(0, 16))}` : ''}</p>
      </div>
    </div>`;

  $('#download-pdf').addEventListener('click', async () => {
    try {
      const response = await api(`/api/invoices/${id}/pdf`, { raw: true });
      if (!response.ok) throw new Error(`PDF failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${invoice.number.replace(/\//g, '-')}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (error) {
      toast(error.message, 'error');
    }
  });

  const payButton = $('#pay');
  if (payButton) {
    payButton.addEventListener('click', async () => {
      payButton.disabled = true;
      try {
        const order = await api('/api/payments/order', {
          method: 'POST',
          body: { invoice_id: invoice.id },
        });
        const callback = await api(`/api/payments/${order.order_id}/simulate`, { method: 'POST' });
        const result = await api('/api/payments/verify', {
          method: 'POST',
          body: {
            invoice_id: invoice.id,
            razorpay_order_id: callback.order_id,
            razorpay_payment_id: callback.payment_id,
            razorpay_signature: callback.signature,
          },
        });
        toast(`Payment ${result.status} — ${inr(result.amount)}. Signature verified.`);
        viewInvoice(id);
      } catch (error) {
        toast(error.message, 'error');
        payButton.disabled = false;
      }
    });
  }

  const cancelButton = $('#cancel');
  if (cancelButton) {
    cancelButton.addEventListener('click', async () => {
      if (!confirm('Cancel this invoice? Stock will be restored and the number is not reused.')) return;
      try {
        await api(`/api/invoices/${id}/cancel`, { method: 'POST' });
        toast('Invoice cancelled.');
        viewInvoice(id);
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  }
}

function groupByRate(lines) {
  const buckets = new Map();
  for (const line of lines) {
    const bucket = buckets.get(line.gst_rate) || {
      gst_rate: line.gst_rate, taxable_value: 0, cgst: 0, sgst: 0, igst: 0, line_total: 0,
    };
    bucket.taxable_value += line.taxable_value;
    bucket.cgst += line.cgst;
    bucket.sgst += line.sgst;
    bucket.igst += line.igst;
    bucket.line_total += line.line_total;
    buckets.set(line.gst_rate, bucket);
  }
  return [...buckets.values()].sort((a, b) => a.gst_rate - b.gst_rate);
}

// --------------------------------------------------------------------------- //
// reports
// --------------------------------------------------------------------------- //
async function viewReports() {
  let report;
  try {
    report = await api('/api/reports/gst');
  } catch (error) {
    $('#view').innerHTML = `<div class="card"><h2>Reports are restricted</h2>
      <p class="muted">${esc(error.message)}</p></div>`;
    return;
  }

  const taxTotal = report.by_rate.reduce((sum, row) => sum + row.tax_total, 0);
  $('#view').innerHTML = `
    <h1>GST report · FY ${esc(report.fy)}</h1>
    <p class="muted">${esc(report.period.from)} → ${esc(report.period.to)} ·
      ${report.invoice_count} invoices · cancelled invoices excluded</p>

    <div class="grid cols-4" style="margin-bottom:1rem">
      ${stat('Taxable value', inr(report.by_rate.reduce((sum, row) => sum + row.taxable_value, 0)), 'all rates')}
      ${stat('Tax payable', inr(taxTotal), 'CGST + SGST + IGST + cess')}
      ${stat('B2B', inr(report.b2b.total), `${report.b2b.invoices} invoices with GSTIN`)}
      ${stat('B2C', inr(report.b2c.total), `${report.b2c.invoices} walk-in invoices`)}
    </div>

    <div class="card">
      <h2>Rate-wise summary</h2>
      <div class="table-wrap"><table>
        <thead><tr><th class="num">GST rate</th><th class="num">Taxable</th><th class="num">CGST</th>
          <th class="num">SGST</th><th class="num">IGST</th><th class="num">Cess</th>
          <th class="num">Total</th></tr></thead>
        <tbody>${report.by_rate.length ? report.by_rate.map((row) => `
          <tr><td class="num">${row.gst_rate}%</td><td class="num">${inr(row.taxable_value)}</td>
            <td class="num">${inr(row.cgst)}</td><td class="num">${inr(row.sgst)}</td>
            <td class="num">${inr(row.igst)}</td><td class="num">${inr(row.cess)}</td>
            <td class="num">${inr(row.total)}</td></tr>`).join('')
          : '<tr><td class="empty" colspan="7">No invoices in this period.</td></tr>'}</tbody>
      </table></div>
    </div>

    <div class="split">
      <div class="card">
        <h2>Intra vs inter state</h2>
        <div class="table-wrap"><table>
          <thead><tr><th>Supply</th><th class="num">Invoices</th><th class="num">CGST</th>
            <th class="num">SGST</th><th class="num">IGST</th></tr></thead>
          <tbody>
            <tr><td>Intra (within ${esc(state.tenant.state_code)})</td>
              <td class="num">${report.intra_state.invoices}</td>
              <td class="num">${inr(report.intra_state.cgst)}</td>
              <td class="num">${inr(report.intra_state.sgst)}</td>
              <td class="num">${inr(report.intra_state.igst)}</td></tr>
            <tr><td>Inter (other states)</td>
              <td class="num">${report.inter_state.invoices}</td>
              <td class="num">${inr(report.inter_state.cgst)}</td>
              <td class="num">${inr(report.inter_state.sgst)}</td>
              <td class="num">${inr(report.inter_state.igst)}</td></tr>
          </tbody></table></div>
        <p class="hintbox" style="margin-top:0.75rem">This is a GSTR-1 shaped summary for review,
          not a filing. Exports, SEZ and reverse-charge supplies are out of scope (see README).</p>
      </div>

      <div class="card">
        <h2>APIs used by this page</h2>
        <p class="muted">Every number above came from here — open the docs and try them:</p>
        <ul style="margin:0;padding-left:1.1rem;font-size:0.86rem">
          <li><code>GET /api/reports/summary?days=30</code></li>
          <li><code>GET /api/reports/gst?fy=2026-27&amp;month=2026-11</code></li>
          <li><code>POST /api/payments/order</code> → <code>POST /api/payments/verify</code></li>
          <li><code>GET /api/invoices/{id}/pdf</code></li>
          <li><a href="/docs" target="_blank" rel="noreferrer">Interactive OpenAPI docs</a></li>
        </ul>
      </div>
    </div>`;
}

// --------------------------------------------------------------------------- //
// settings
// --------------------------------------------------------------------------- //
async function viewSettings() {
  const isOwner = state.user.role === 'owner';
  const [users, health] = await Promise.all([
    isOwner ? api('/api/auth/users').catch(() => []) : Promise.resolve([]),
    fetch('/health').then((response) => response.json()),
  ]);

  $('#view').innerHTML = `
    <h1>Settings</h1>
    <div class="split">
      <div class="card">
        <h2>Shop</h2>
        <p><strong>${esc(state.tenant.name)}</strong><br>
          <span class="muted">GSTIN ${esc(state.tenant.gstin || 'unregistered')} · state ${esc(state.tenant.state_code)}</span></p>
        <p class="muted">You are signed in as <strong>${esc(state.user.email)}</strong> (${esc(state.user.role)}).</p>
        <h3 style="margin-top:1rem">Payment provider</h3>
        <p class="muted">Mode: <strong>${esc(health.payments.mode)}</strong>. ${
          health.payments.live_keys
            ? 'Test keys detected — orders are created on Razorpay test mode.'
            : 'No keys configured, so orders are simulated locally with the same HMAC scheme.'}</p>
        <p class="hintbox">This project never accepts live keys. Set
          <code>RAZORPAY_KEY_ID</code>/<code>RAZORPAY_KEY_SECRET</code> with <code>rzp_test_…</code>
          values to call the real test API.</p>
      </div>

      <div class="card">
        <h2>Team</h2>
        ${isOwner ? `
          <div class="table-wrap"><table>
            <thead><tr><th>Email</th><th>Role</th></tr></thead>
            <tbody>${users.map((user) => `<tr><td>${esc(user.email)}</td>
              <td><span class="pill">${esc(user.role)}</span></td></tr>`).join('')}</tbody>
          </table></div>
          <form id="invite-form" class="row" style="margin-top:0.9rem">
            <label class="field"><span>Email</span><input name="email" type="email" required /></label>
            <label class="field"><span>Role</span>
              <select name="role"><option value="staff">staff (billing)</option>
                <option value="accountant">accountant (read-only)</option></select></label>
            <label class="field"><span>Temp password</span>
              <input name="password" type="text" minlength="8" value="secret123" required /></label>
            <div style="flex:0 0 auto"><button class="btn primary" type="submit">Invite</button></div>
          </form>` : '<p class="muted">Only the owner can manage the team.</p>'}
        <h3 style="margin-top:1rem">What each role can do</h3>
        <ul class="muted" style="margin:0;padding-left:1.1rem;font-size:0.85rem">
          <li><strong>owner</strong> — everything, including catalogue, cancellation and team</li>
          <li><strong>staff</strong> — bill customers, take payments, adjust stock; no reports</li>
          <li><strong>accountant</strong> — read everything, write nothing</li>
        </ul>
      </div>
    </div>`;

  const form = $('#invite-form');
  if (form) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(form).entries());
      try {
        await api('/api/auth/users', {
          method: 'POST',
          body: { name: data.role.title(), email: data.email, password: data.password, role: data.role },
        });
        toast(`${data.email} can now sign in.`);
        viewSettings();
      } catch (error) {
        toast(error.message, 'error');
      }
    });
  }
}

// --------------------------------------------------------------------------- //
// router
// --------------------------------------------------------------------------- //
async function route() {
  const hash = location.hash.replace('#/', '') || (state.token ? 'dashboard' : 'login');
  const [page, param] = hash.split('/');
  setChrome();

  if (!state.token && page !== 'login') {
    viewLogin('login');
    return;
  }
  if (state.token && page === 'login') {
    location.hash = '#/dashboard';
    return route();
  }

  $('#view').innerHTML = '<div class="card"><p class="muted">Loading…</p></div>';
  try {
    if (page === 'dashboard') await viewDashboard();
    else if (page === 'items') await viewItems();
    else if (page === 'invoices') await viewInvoices();
    else if (page === 'invoice') await viewInvoice(param);
    else if (page === 'reports') await viewReports();
    else if (page === 'settings') await viewSettings();
    else if (page === 'login') viewLogin('login');
    else {
      $('#view').innerHTML = '<div class="card"><h2>Not found</h2><p class="muted">Pick a tab above.</p></div>';
    }
  } catch (error) {
    $('#view').innerHTML = `<div class="card"><h2>Something went wrong</h2>
      <p class="muted">${esc(error.message)}</p></div>`;
  }
}

async function boot() {
  try {
    state.meta = await fetch('/api/meta').then((response) => response.json());
  } catch { /* offline metadata is not fatal */ }
  if (state.token) {
    try {
      // A reload has a token but no in-memory identity: rehydrate both halves.
      const [me, tenant] = await Promise.all([api('/api/auth/me'), api('/api/auth/tenant')]);
      state.user = me;
      state.tenant = tenant;
    } catch {
      signOut();
      return;
    }
  }
  setChrome();
  route();
}

$('#logout').addEventListener('click', () => signOut('Signed out.'));
window.addEventListener('hashchange', route);
boot();
