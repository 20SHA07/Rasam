'use strict';

// Dependency-free behavioral tests. A small DOM mock exercises the application
// event handlers; it cannot verify actual layout, PDF rendering, or browser APIs.
// Run from any directory: node path/to/tests/test_ai_frontend.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { inflateRawSync } = require('node:zlib');

const parent = path.resolve(__dirname, '..');
const root = fs.existsSync(path.join(parent, 'app.js')) ? parent : path.join(parent, 'source');
const source = name => fs.readFileSync(path.join(root, name), 'utf8');
const html = source('index.html');
const appSource = source('app.js');
const bridgeSource = source('ai-client.js');
const exportSource = source('export.js');
const fieldNames = ['supplier', 'invoiceNumber', 'date', 'currency', 'net', 'vat', 'total'];
const tests = [];
const test = (name, run) => tests.push({ name, run });
const flush = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function reading(overrides = {}) {
  return {
    is_invoice: true, supplier: 'شركة الاختبار', invoiceNumber: 'TEST-001',
    date: '2026-09-21', currency: 'SAR', net: '100.00', vat: '15.00', total: '115.00',
    warnings: [], field_warnings: [], line_items: [], ...overrides
  };
}
function file(name = 'supplier-invoice.png') {
  const result = new Blob([Buffer.from('89504e470d0a1a0a00000000', 'hex')], { type: 'image/png' });
  result.name = name;
  result.lastModified = 1000;
  return result;
}

async function app(options = {}) {
  const objects = new Map();
  const downloads = [];
  const calls = [];
  let nextObject = 0;
  class Element {
    constructor(id) {
      this.id = id; this.value = ''; this.checked = false; this.disabled = false;
      this.hidden = false; this.dataset = {}; this.listeners = new Map(); this.children = [];
      this.attributes = {}; this.html = ''; this.text = ''; this.selectorCache = new Map();
      const classes = new Set();
      this.classList = {
        add: name => classes.add(name), remove: name => classes.delete(name),
        toggle(name, force) {
          const enabled = force === undefined ? !classes.has(name) : force;
          if (enabled) classes.add(name); else classes.delete(name);
          return enabled;
        },
        contains: name => classes.has(name)
      };
    }
    set innerHTML(value) {
      this.html = String(value); this.text = this.html.replace(/<[^>]*>/g, '');
      this.children = []; this.selectorCache.clear();
    }
    get innerHTML() { return this.html; }
    set textContent(value) { this.text = String(value); }
    get textContent() { return this.text; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    addEventListener(name, callback) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(callback);
    }
    async fire(name, event = {}) {
      for (const callback of this.listeners.get(name) || []) {
        await callback({ preventDefault() {}, target: this, ...event });
      }
    }
    appendChild(element) { this.children.push(element); return element; }
    remove() {}
    focus() { this.focused = true; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    click() {
      if (this.disabled) return;
      if (this.href && this.download) downloads.push({ blob: objects.get(this.href), filename: this.download });
      else return this.fire('click');
    }
    querySelectorAll(selector) {
      if (this.selectorCache.has(selector)) return this.selectorCache.get(selector);
      const definition = {
        '[data-id]': ['data-id', 'id'],
        '[data-apply-ai]': ['data-apply-ai', 'applyAi']
      }[selector];
      if (!definition) return [];
      const [attribute, key] = definition;
      const pattern = new RegExp('<button\\b[^>]*\\b' + attribute + '="([^"]+)"[^>]*>', 'g');
      const values = [...this.html.matchAll(pattern)].map(match => {
        const element = new Element('dynamic-button');
        element.dataset[key] = match[1];
        element.disabled = /\sdisabled(?:\s|>|=)/.test(match[0]);
        return element;
      });
      this.selectorCache.set(selector, values);
      return values;
    }
  }
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], new Element(match[1])]));
  const filters = ['all', 'review', 'approved'].map(name => {
    const element = new Element('filter-' + name); element.dataset.filter = name; return element;
  });
  const document = {
    getElementById(id) { assert(elements.has(id), 'Missing DOM element: ' + id); return elements.get(id); },
    querySelectorAll: selector => selector === '[data-filter]' ? filters : [],
    createElement: tag => new Element(tag), body: new Element('body')
  };
  const context = {
    document, console, TextEncoder, Blob,
    URL: {
      createObjectURL(blob) { const url = 'blob:mock-' + (++nextObject); objects.set(url, blob); return url; },
      revokeObjectURL: url => objects.delete(url)
    },
    setTimeout() { return 0; }, clearTimeout() {}, addEventListener() {},
    RasamAI: {
      status: options.status || (async () => ({ configured: true, localServer: true, model: 'test-model', csrf_token: 'session-token' })),
      async extract(...args) {
        calls.push(args);
        return options.extract ? options.extract(...args) : reading();
      }
    }
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(exportSource, context, { filename: 'export.js' });
  vm.runInContext(appSource, context, { filename: 'app.js' });
  await flush(); // The initial connection check is asynchronous.
  const get = id => document.getElementById(id);
  async function fill(id, value) { get(id).value = value; await get(id).fire('input'); }
  async function fillInvoice(values = reading()) {
    for (const name of fieldNames) if (values[name] != null) await fill(name, values[name]);
  }
  async function approve() {
    get('review-confirm').checked = true;
    await get('review-confirm').fire('change');
    await get('invoice-form').fire('submit');
  }
  async function upload(uploaded = file()) {
    await get('file-input').fire('change', { target: { files: [uploaded] } });
    return uploaded;
  }
  async function select(id) {
    const button = get('invoice-list').querySelectorAll('[data-id]').find(button => button.dataset.id === id);
    assert(button, 'Invoice should be in the inbox: ' + id);
    await button.click();
  }
  return { get, fill, fillInvoice, approve, upload, select, calls, downloads, objects,
    read: () => get('read-ai-button').click(),
    values: () => Object.fromEntries(fieldNames.map(name => [name, get(name).value]))
  };
}

function zipEntry(bytes, wanted) {
  const buffer = Buffer.from(bytes);
  let offset = 0;
  while (buffer.readUInt32LE(offset) === 0x04034b50) {
    const compression = buffer.readUInt16LE(offset + 8);
    const size = buffer.readUInt32LE(offset + 18);
    const nameLength = buffer.readUInt16LE(offset + 26);
    const extraLength = buffer.readUInt16LE(offset + 28);
    const name = buffer.subarray(offset + 30, offset + 30 + nameLength).toString();
    const start = offset + 30 + nameLength + extraLength;
    const data = buffer.subarray(start, start + size);
    if (name === wanted) {
      assert([0, 8].includes(compression), 'Supported ZIP compression');
      return (compression === 8 ? inflateRawSync(data) : data).toString('utf8');
    }
    offset = start + size;
  }
  assert.fail('Missing ZIP entry: ' + wanted);
}

test('Samples still require approval; amount errors and later edits prevent export', async () => {
  const ui = await app();
  assert.equal(ui.get('supplier').value, 'Al Noor Stationery LLC');
  assert(ui.get('read-ai-button').disabled);
  await ui.get('invoice-form').fire('submit');
  assert.match(ui.get('form-errors').textContent, /Confirm that you checked/);
  await ui.fill('total', '2242.51');
  await ui.approve();
  assert.match(ui.get('form-errors').textContent, /Net amount \+ tax must equal/);
  assert(ui.get('export-button').disabled);
  assert.match(ui.get('source-preview').innerHTML, /2,242\.50/);
  await ui.fill('total', '2242.50');
  await ui.approve();
  assert.equal(ui.get('selected-status').textContent, 'Approved');
  await ui.fill('notes', 'Changed after approval');
  assert.equal(ui.get('selected-status').textContent, 'Needs review');
  assert.equal(ui.get('review-confirm').checked, false);
  assert(ui.get('export-button').disabled);
  assert.equal(ui.calls.length, 0);
});

test('An uploaded file fills empty fields and exports human-reviewed AI provenance', async () => {
  const ui = await app();
  const uploaded = await ui.upload();
  for (const name of fieldNames) assert.equal(ui.get(name).value, '', name);
  assert(!ui.get('read-ai-button').disabled);
  await ui.read();
  assert.equal(ui.calls[0][0], uploaded, 'AI receives the original File/Blob');
  assert.equal(ui.calls[0][1], 'image/png');
  assert.equal(ui.calls[0][2], 'session-token');
  for (const name of fieldNames) assert.equal(ui.get(name).value, reading()[name], name);
  assert.equal(ui.get('selected-status').textContent, 'Needs review');
  assert(ui.get('export-button').disabled);
  await ui.approve();
  await ui.get('export-button').click();
  assert.equal(ui.downloads.length, 1);
  assert.match(ui.downloads[0].filename, /\.xlsx$/);
  const sheet = zipEntry(await ui.downloads[0].blob.arrayBuffer(), 'xl/worksheets/sheet1.xml');
  assert.match(sheet, /AI-assisted, human reviewed/);
  assert.match(sheet, /شركة الاختبار/);
  assert.match(sheet, /supplier-invoice\.png/);
  assert.match(sheet, /<c r="E5"[^>]*><v>100<\/v>/);
  assert.doesNotMatch(sheet, /Al Noor Stationery LLC/, 'Unapproved sample must not export');
});

test('Existing values are preserved and a conflicting suggestion requires explicit use', async () => {
  const ui = await app();
  await ui.upload();
  await ui.fill('supplier', 'My verified supplier');
  await ui.read();
  assert.equal(ui.get('supplier').value, 'My verified supplier');
  assert.equal(ui.get('total').value, '115.00');
  await ui.approve();
  assert.equal(ui.get('selected-status').textContent, 'Approved');
  const suggestion = ui.get('ai-insight-body').querySelectorAll('[data-apply-ai]').find(button => button.dataset.applyAi === 'supplier');
  assert(suggestion, 'Conflicting value must remain a visible suggestion');
  await suggestion.click();
  assert.equal(ui.get('supplier').value, 'شركة الاختبار');
  assert.equal(ui.get('selected-status').textContent, 'Needs review');
  assert.equal(ui.get('review-confirm').checked, false);
  assert(ui.get('export-button').disabled);
});

test('Edits and intentional clearing during an AI request survive its response', async () => {
  const pending = deferred();
  const ui = await app({ extract: () => pending.promise });
  await ui.upload();
  await ui.fill('invoiceNumber', 'USER-001');
  const request = ui.read();
  await ui.fill('supplier', 'Typed while reading');
  await ui.fill('invoiceNumber', '');
  pending.resolve(reading());
  await request;
  assert.equal(ui.get('supplier').value, 'Typed while reading');
  assert.equal(ui.get('invoiceNumber').value, '', 'Intentionally cleared field must not be refilled');
  assert.match(ui.get('ai-insight-body').innerHTML, /TEST-001/);
  assert.equal(ui.get('review-confirm').checked, false);
});

test('Changing selected invoice while reading never applies the result to that selection', async () => {
  const pending = deferred();
  const ui = await app({ extract: () => pending.promise });
  await ui.upload(file('first.png'));
  const request = ui.read();
  await ui.upload(file('second.png'));
  await ui.fill('supplier', 'Second invoice supplier');
  pending.resolve(reading());
  await request;
  assert.equal(ui.get('supplier').value, 'Second invoice supplier');
  assert.equal(ui.get('invoiceNumber').value, '');
  assert.equal(ui.get('total').value, '');
  await ui.select('RAS-0002');
  assert.equal(ui.get('supplier').value, 'شركة الاختبار');
  assert.equal(ui.get('total').value, '115.00');
});

test('Approval is blocked for a pending read, even through direct form submission', async () => {
  const pending = deferred();
  const ui = await app({ extract: () => pending.promise });
  await ui.upload();
  await ui.fillInvoice();
  await ui.approve();
  const request = ui.read();
  assert(ui.get('approve-button').disabled);
  assert(ui.get('export-button').disabled, 'Starting a new read revokes prior approval');
  await ui.approve();
  assert.match(ui.get('form-errors').textContent, /Wait for AI reading/);
  assert.equal(ui.get('selected-status').textContent, 'Reading…');
  pending.resolve(reading());
  await request;
  assert.equal(ui.get('selected-status').textContent, 'Needs review');
  assert.equal(ui.get('review-confirm').checked, false);
});

for (const code of ['request_failed', 'authentication', 'authentication_failed', 'invalid_api_key']) {
  test('Failed AI read preserves values and revokes approval: ' + code, async () => {
    const error = Object.assign(new Error('Test service failure'), { code });
    const ui = await app({ extract: async () => { throw error; } });
    await ui.upload();
    await ui.fillInvoice();
    await ui.approve();
    const before = ui.values();
    await ui.read();
    assert.deepEqual(ui.values(), before);
    assert.equal(ui.get('selected-status').textContent, 'Needs review');
    assert.equal(ui.get('review-confirm').checked, false);
    assert(ui.get('export-button').disabled);
    assert.match(ui.get('ai-feedback').textContent, /Test service failure/);
    if (code !== 'request_failed') {
      assert(ui.get('read-ai-button').disabled);
      assert.match(ui.get('ai-connection-title').textContent, /key needs attention/);
    }
  });
}

test('A non-invoice result never populates details or offers field application', async () => {
  const ui = await app({ extract: async () => reading({ is_invoice: false }) });
  await ui.upload();
  await ui.fill('supplier', 'Keep my entry');
  const before = ui.values();
  await ui.read();
  assert.deepEqual(ui.values(), before);
  assert.match(ui.get('ai-feedback').textContent, /could not be treated as a single invoice/);
  assert.equal(ui.get('ai-insight-body').querySelectorAll('[data-apply-ai]').length, 0);
  assert(ui.get('export-button').disabled);
});

test('AI text is escaped in warnings, field notes, suggestions, line items, and invoice list', async () => {
  const payload = '<img src=x onerror="alert(1)"><script>alert(2)</script>&';
  const ui = await app({ extract: async () => reading({
    supplier: payload, warnings: [payload], field_warnings: [{ field: 'supplier', message: payload }],
    line_items: [{ description: payload, quantity: payload, unit_price: payload, net_amount: payload }]
  }) });
  await ui.upload();
  await ui.fill('supplier', 'Existing supplier');
  await ui.read();
  for (const id of ['ai-feedback', 'ai-insight-body']) {
    const markup = ui.get(id).innerHTML;
    assert.doesNotMatch(markup, /<img|<script|<\/script>/i, id);
    assert.match(markup, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/, id);
    assert.match(markup, /&lt;script&gt;alert\(2\)&lt;\/script&gt;&amp;/, id);
  }
  const suggestion = ui.get('ai-insight-body').querySelectorAll('[data-apply-ai]').find(button => button.dataset.applyAi === 'supplier');
  await suggestion.click();
  assert.equal(ui.get('supplier').value, payload, 'Input value remains text');
  assert.equal(ui.get('selected-supplier').textContent, payload, 'Header uses textContent');
  assert.doesNotMatch(ui.get('invoice-list').innerHTML, /<img|<script/i);
});

test('Duplicate uploads and duplicate supplier/invoice pairs still need attention', async () => {
  const ui = await app();
  const uploaded = await ui.upload();
  await ui.upload(uploaded);
  assert.equal(ui.get('inbox-count').textContent, '2');
  assert.match(ui.get('toast').textContent, /already in the inbox/);
  await ui.fillInvoice(reading({ supplier: 'Al Noor Stationery LLC', invoiceNumber: 'INV-2026-0481' }));
  await ui.approve();
  assert.match(ui.get('form-errors').textContent, /already exist in the inbox/);
  assert(ui.get('export-button').disabled);
});

function bridge(options = {}) {
  const requests = [];
  const reads = [];
  class FileReader {
    readAsDataURL(input) {
      reads.push(input);
      this.result = 'data:image/png;base64,aW52b2ljZQ==';
      queueMicrotask(() => this.onload());
    }
  }
  const context = {
    console, AbortController, TypeError, FileReader,
    location: options.location || { protocol: 'http:', hostname: 'localhost' },
    RASAM_INLINE_PREVIEW: options.preview || false,
    setTimeout() { return 0; }, clearTimeout() {},
    async fetch(url, request) {
      requests.push({ url, request });
      if (options.fetch) return options.fetch(url, request);
      return { ok: true, json: async () => url === '/api/status' ? { configured: true, csrf_token: 'token', model: 'test-model' } : { invoice: reading() } };
    }
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(bridgeSource, context, { filename: 'ai-client.js' });
  return { api: context.RasamAI, requests, reads };
}

test('Bridge sends the file only to localhost API with a session token, never an API key', async () => {
  const client = bridge();
  const status = await client.api.status();
  assert(status.configured && status.localServer);
  const uploaded = file();
  const result = await client.api.extract(uploaded, 'image/png', status.csrf_token);
  assert.equal(result.supplier, 'شركة الاختبار');
  assert.equal(client.reads[0], uploaded);
  const request = client.requests[1];
  assert.equal(request.url, '/api/extract');
  assert.equal(request.request.method, 'POST');
  assert.equal(request.request.credentials, 'same-origin');
  assert.equal(request.request.headers['X-Rasam-Token'], 'token');
  assert.deepEqual(JSON.parse(request.request.body), { filename: uploaded.name, mime_type: 'image/png', data_base64: 'aW52b2ljZQ==' });
  assert(!Object.keys(request.request.headers).some(key => /authorization|api.key/i.test(key)));
  assert.doesNotMatch(html, /<input\b[^>]*(?:api[-_]?key|type=["']password)/i);
  assert.doesNotMatch(appSource + bridgeSource, /localStorage|sessionStorage|Bearer\s|api\.openai\.com/);
});

for (const [label, options] of [
  ['direct HTML', { location: { protocol: 'file:', hostname: '' } }],
  ['chat preview', { preview: true }],
  ['remote host', { location: { protocol: 'https:', hostname: 'example.com' } }]
]) {
  test('Bridge avoids network calls in ' + label, async () => {
    const client = bridge(options);
    assert.equal((await client.api.status()).configured, false);
    await assert.rejects(() => client.api.extract(file(), 'image/png', 'token'), /localhost app/);
    assert.equal(client.requests.length, 0);
    assert.equal(client.reads.length, 0);
  });
}

test('Bridge blocks extraction without a session token', async () => {
  const client = bridge();
  await assert.rejects(() => client.api.extract(file(), 'image/png', ''), /Check the AI connection/);
  assert.equal(client.requests.length, 0);
});

test('Bridge rejects malformed results before they can reach invoice fields', async () => {
  for (const invoice of [undefined, reading({ net: 100 }), reading({ warnings: null }), reading({ supplier: undefined })]) {
    const client = bridge({ fetch: async () => ({ ok: true, json: async () => ({ invoice }) }) });
    await assert.rejects(() => client.api.extract(file(), 'image/png', 'token'), /unreadable result|invalid field/);
  }
});

test('Bridge preserves server authentication error codes for the connection UI', async () => {
  const client = bridge({ fetch: async () => ({ ok: false, json: async () => ({ error: 'Check the server API key.', code: 'authentication_failed' }) }) });
  await assert.rejects(() => client.api.extract(file(), 'image/png', 'token'), error => error.code === 'authentication_failed' && /API key/.test(error.message));
});

(async () => {
  let failed = 0;
  for (const { name, run } of tests) {
    try { await run(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + '\n' + error.stack); }
  }
  console.log(`\n${tests.length - failed}/${tests.length} tests passed (DOM mock and mocked local API; no real API calls).`);
  console.log('Not verified: visual layout, real image/PDF rendering, native browser downloads, or live model extraction.');
  process.exitCode = failed ? 1 : 0;
})();
