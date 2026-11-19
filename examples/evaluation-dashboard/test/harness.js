// The browser check of the evaluation dashboard (run.py). It loads the dashboard in a frame of
// the same origin at a phone width and at a desktop width, and compares the page with the API.
// It sends the result to the collector of run.py with a navigation, because the API is
// read-only.
const params = new URLSearchParams(location.search);
const collector = Number(params.get('collector'));
const broken = params.get('broken');
const WAIT_MS = 20000;
// The token of the server, from the fragment of the address that run.py opens.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get('token') ?? '';
const WIDTHS = [['phone', 360], ['desktop', 1280]];

function send(result) {
  const text = encodeURIComponent(JSON.stringify(result));
  location.href = `http://127.0.0.1:${collector}/result?r=${text}`;
}

window.addEventListener('error', (event) => send({ pass: false, error: String(event.message) }));
window.addEventListener('unhandledrejection', (event) => send({ pass: false, error: String(event.reason) }));

async function api(path) {
  const response = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  return response.json();
}

function until(test, what) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const look = () => {
      const value = test();
      if (value) resolve(value);
      else if (Date.now() - started > WAIT_MS) reject(new Error(`no ${what} after ${WAIT_MS} ms`));
      else setTimeout(look, 100);
    };
    look();
  });
}

// The text of a node and of each open shadow root in it.
function deepText(node) {
  let text = '';
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) text += child.textContent;
    else if (child.nodeType === Node.ELEMENT_NODE) text += ` ${deepText(child)}`;
  }
  if (node.shadowRoot) text += ` ${deepText(node.shadowRoot)}`;
  return text;
}

function refusals(node) {
  let count = 0;
  for (const el of node.querySelectorAll('*')) {
    if (el.shadowRoot) count += el.shadowRoot.querySelectorAll('.refused').length + refusals(el.shadowRoot);
  }
  return count;
}

function press(box) {
  const control = box.querySelector('[slot="actions"]');
  const button = control?.shadowRoot?.querySelector('button');
  if (!button) throw new Error('no Open button');
  button.click();
}

function load(name, width) {
  const frame = document.createElement('iframe');
  frame.className = name;
  frame.title = `Dashboard at ${width} px`;
  frame.src = `/#token=${encodeURIComponent(TOKEN)}`;
  document.getElementById('frames').append(frame);
  return frame;
}

async function check(name, width, runs, gates) {
  const frame = load(name, width);
  const checks = {};
  const doc = await until(() => {
    const d = frame.contentDocument;
    const state = d?.getElementById('main')?.dataset.state;
    return state === 'ready' || state === 'error' ? d : null;
  }, 'ready page');
  const main = doc.getElementById('main');
  checks.ready = main.dataset.state === 'ready';
  checks.run_cards = doc.querySelectorAll('[data-run]').length === Math.min(runs.length, 50);
  checks.gate_cards = doc.querySelectorAll('[data-gate]').length === Math.min(gates.length, 50);
  const box = doc.querySelector(`[data-run="${CSS.escape(broken)}"]`);
  checks.broken_seal_marked = box?.dataset.seal === 'broken' && box?.dataset.verdict === 'cannot be used'
    && deepText(box).includes('broken');
  const verdicts = runs.every((run) => {
    const card = doc.querySelector(`[data-run="${CSS.escape(run.id)}"]`);
    return card?.dataset.verdict === (run.verdict ?? 'cannot be used') && card.dataset.seal === run.seal;
  });
  checks.run_verdicts_match_api = verdicts;
  const gate = gates[0];
  const gateBox = doc.querySelector(`[data-gate="${CSS.escape(gate.id)}"]`);
  checks.gate_verdict_and_subject = gateBox?.dataset.verdict === gate.verdict
    && deepText(gateBox).includes(gate.subject);
  checks.no_refusal = refusals(doc) === 0;
  checks.no_side_scroll = doc.documentElement.scrollWidth <= doc.documentElement.clientWidth;

  // Open the first run with an intact seal: the details show its findings.
  const run = runs.find((r) => r.seal === 'intact');
  const findings = await api(`/runs/${encodeURIComponent(run.id)}/findings`);
  press(doc.querySelector(`[data-run="${CSS.escape(run.id)}"]`));
  const detail = doc.getElementById('detail');
  await until(() => detail.dataset.run === run.id && detail.dataset.state !== 'loading', 'run details');
  checks.open_run = detail.dataset.state === 'ready'
    && detail.dataset.findings === String(findings.findings.findings.length)
    && deepText(detail).includes('findings.json is the file of the seal.');

  // Open the gate run: the details show the verdict of each test.
  press(gateBox);
  const result = (await api(`/gates/${encodeURIComponent(gate.id)}`)).result;
  await until(() => detail.dataset.gate === gate.id && detail.dataset.state !== 'loading', 'gate details');
  const text = deepText(detail);
  checks.open_gate = detail.dataset.state === 'ready'
    && detail.dataset.tests === String(result.tests.length)
    && result.tests.every((t) => text.includes(t.name) && text.includes(t.test));
  checks.no_side_scroll_after_open = doc.documentElement.scrollWidth <= doc.documentElement.clientWidth;

  // Open the run and then at once the gate run: a late answer for the run does not change the
  // panel of the gate run.
  const children = detail.children.length;
  press(doc.querySelector(`[data-run="${CSS.escape(run.id)}"]`));
  press(gateBox);
  await until(() => detail.dataset.gate === gate.id && detail.dataset.state !== 'loading', 'gate details');
  await new Promise((resolve) => setTimeout(resolve, 1500));
  checks.late_answer_dropped = detail.dataset.gate === gate.id && detail.dataset.run === undefined
    && detail.dataset.state === 'ready' && detail.children.length === children;
  checks.no_refusal_after_open = refusals(doc) === 0;
  return { width, checks, pass: Object.values(checks).every(Boolean) };
}

async function start() {
  const runs = (await api('/runs')).runs;
  const gates = (await api('/gates')).gates;
  const out = {};
  for (const [name, width] of WIDTHS) {
    try {
      out[name] = await check(name, width, runs, gates);
    } catch (error) {
      out[name] = { width, pass: false, error: String(error.message) };
    }
  }
  send({ pass: Object.values(out).every((r) => r.pass), widths: out });
}

start();
