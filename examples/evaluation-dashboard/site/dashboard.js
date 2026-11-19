// The evaluation dashboard of Nookku. It reads only the read-only API of the server that serves
// it (docs/reference/api.md), and it shows the data with the components of the mugham kit.
// No string of the API goes into markup: the kit components and textContent show each value
// as text.
import { define } from './mugham/src/components/index.js';
import { createKit, fill } from './mugham/src/kit.js';

define();
const kit = createKit({ actor: { type: 'system', id: 'nookku' } });
const API = '/api/v1';
const MAX_ROWS = 500;
const MAX_CARDS = 50;
// The limits of the kit sizes (catalog/schema/defaults.json of the kit).
const SHORT = 40;
const LINE = 80;
const TITLE = 120;
const SUMMARY = 200;
const CELL = 500;
const TEXT = 10000;
const NO_VERDICT = 'cannot be used';
// `nookku dashboard` prints the address of the page with its token in the fragment (#token=...).
// A browser does not send the fragment to a server. Each API request sends the token.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get('token') ?? '';
// The number of the current selection. A response of an older selection does not change the panel.
let selection = 0;

const main = document.getElementById('main');
const note = document.getElementById('note');
const detail = document.getElementById('detail');

function clip(value, size) {
  const text = value === null || value === undefined ? '-' : String(value);
  return text.length > size ? `${text.slice(0, size - 1)}…` : text;
}

function when(seconds) {
  if (typeof seconds !== 'number') return '-';
  return new Date(seconds * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

function stateOf(verdict) {
  if (verdict === 'pass') return 'passed';
  if (verdict === 'fail') return 'failed';
  return 'unknown';
}

async function get(path) {
  const headers = { Accept: 'application/json', Authorization: `Bearer ${TOKEN}` };
  const response = await fetch(API + path, { headers });
  const data = await response.json();
  if (!response.ok) throw new Error(`${path}: ${data.error ?? response.status}`);
  return data;
}

function fact(label, value) {
  return fill('fact', { label: clip(label, SHORT), value: clip(value, SUMMARY) });
}

function wrapper(parent, keys) {
  const box = document.createElement('div');
  for (const [key, value] of Object.entries(keys)) box.dataset[key] = String(value ?? '');
  parent.append(box);
  return box;
}

function openButton(card, label, open) {
  const button = kit.mount('button', { label, emphasis: 'secondary' }, { parent: card, slot: 'actions' });
  button.addEventListener('mu-press', open);
  return button;
}

function sealText(seal) {
  if (seal === 'intact') return 'intact';
  if (seal === 'broken') return 'broken: a file changed after the seal';
  if (seal === 'none') return 'none: the run has no seal';
  return clip(seal, SUMMARY);
}

function showRuns(runs) {
  const section = document.getElementById('runs');
  const rows = runs.slice(0, MAX_ROWS).map((run) => fill('table-row', {
    cells: [run.id, when(run.started), run.seal, run.verdict ?? NO_VERDICT].map((cell) => clip(cell, CELL)),
    status: run.verdict ?? NO_VERDICT,
  }));
  kit.mount('table', {
    label: `Runs of the project (${runs.length})`,
    columns: ['Run', 'Started', 'Seal', 'Verdict'],
    rows,
    status_values: ['pass', 'fail', NO_VERDICT],
    sort_key: 1,
    sort_direction: 'descending',
  }, { parent: section });
  const cards = document.createElement('div');
  cards.className = 'cards';
  section.append(cards);
  for (const run of runs.slice(0, MAX_CARDS)) {
    const box = wrapper(cards, { run: run.id, seal: run.seal, verdict: run.verdict ?? NO_VERDICT });
    const problems = [run.verdict_problem, ...(run.errors ?? [])].filter(Boolean);
    const card = kit.mount('card', {
      title: clip(run.id, TITLE),
      status: clip(run.verdict ?? NO_VERDICT, TITLE),
      ...(problems.length ? { summary: clip(problems.join(' '), 1000) } : {}),
      facts: [
        fact('Started', when(run.started)),
        fact('Turns', run.turns),
        fact('Breaks', run.breaks),
        fact('Findings', run.findings),
        fact('Seal', sealText(run.seal)),
        fact('State', run.state),
      ],
    }, { parent: box });
    openButton(card, 'Open', () => openRun(run.id));
  }
}

function showGates(gates) {
  const section = document.getElementById('gates');
  if (!gates.length) {
    kit.mount('text', { text: 'The project has no gate run.', variant: 'caption' }, { parent: section });
    return;
  }
  const cards = document.createElement('div');
  cards.className = 'cards';
  section.append(cards);
  for (const gate of gates.slice(0, MAX_CARDS)) {
    const box = wrapper(cards, { gate: gate.id, seal: gate.seal, verdict: gate.verdict ?? NO_VERDICT });
    const card = kit.mount('card', {
      title: clip(gate.id, TITLE),
      status: clip(gate.verdict ?? NO_VERDICT, TITLE),
      ...(gate.problem ? { summary: clip(gate.problem, 1000) } : {}),
      facts: [
        fact('Subject', gate.subject),
        fact('Tests', gate.tests),
        fact('Seal', sealText(gate.seal)),
      ],
    }, { parent: box });
    openButton(card, 'Open', () => openGate(gate.id));
  }
}

function clearDetail(keys) {
  selection += 1;
  detail.replaceChildren(document.getElementById('detail-title'));
  detail.dataset.state = 'loading';
  for (const key of ['run', 'gate']) delete detail.dataset[key];
  Object.assign(detail.dataset, keys);
  return selection;
}

function sealedText(name, sealed) {
  return sealed
    ? `${name} is the file of the seal.`
    : `${name} is not the file of the seal. Do not trust it.`;
}

async function openRun(id) {
  const mine = clearDetail({ run: id });
  try {
    const [verdict, found, evaluation] = await Promise.all([
      get(`/runs/${encodeURIComponent(id)}/verdict`),
      get(`/runs/${encodeURIComponent(id)}/findings`),
      get(`/runs/${encodeURIComponent(id)}/evaluation`),
    ]);
    if (mine !== selection) return;
    const stack = kit.mount('stack', { label: clip(`Run ${id}`, LINE), gap: 'medium' }, { parent: detail });
    const report = verdict.verdict;
    kit.mount('status', {
      state: stateOf(report?.verdict),
      text: clip(report ? `Verdict: ${report.verdict}` : `Verdict: ${NO_VERDICT}. ${verdict.problem}`, SUMMARY),
    }, { parent: stack });
    kit.mount('text', { text: sealedText('findings.json', found.sealed), variant: 'caption' }, { parent: stack });
    if (found.error) kit.mount('text', { text: clip(found.error, TEXT) }, { parent: stack });
    const findings = Array.isArray(found.findings?.findings) ? found.findings.findings : [];
    kit.mount('table', {
      label: clip(`Findings (${findings.length})`, TITLE),
      columns: ['Check', 'Turn', 'Detail'],
      rows: findings.slice(0, MAX_ROWS).map((f) => fill('table-row', {
        cells: [f.check, f.turn, f.detail].map((cell) => clip(cell, CELL)),
      })),
    }, { parent: stack });
    if (evaluation.report === null) {
      kit.mount('text', { text: 'The run has no evaluation report.', variant: 'caption' }, { parent: stack });
    } else {
      kit.mount('text', { text: 'Evaluation report (a model wrote it)', variant: 'strong' }, { parent: stack });
      kit.mount('text', { text: sealedText('report.md', evaluation.sealed), variant: 'caption' }, { parent: stack });
      kit.mount('text', { text: clip(evaluation.report, TEXT), clamp: 12 }, { parent: stack });
    }
    detail.dataset.findings = String(findings.length);
    detail.dataset.state = 'ready';
  } catch (error) {
    if (mine !== selection) return;
    kit.mount('status', { state: 'unknown', text: clip(String(error.message), SUMMARY) }, { parent: detail });
    detail.dataset.state = 'error';
  }
}

async function openGate(id) {
  const mine = clearDetail({ gate: id });
  try {
    const data = await get(`/gates/${encodeURIComponent(id)}`);
    if (mine !== selection) return;
    const stack = kit.mount('stack', { label: clip(`Gate run ${id}`, LINE), gap: 'medium' }, { parent: detail });
    const result = data.result;
    kit.mount('status', {
      state: stateOf(result?.verdict),
      text: clip(result ? `Verdict: ${result.verdict}. Subject: ${result.subject}` : `Verdict: ${NO_VERDICT}. ${data.problem}`, SUMMARY),
    }, { parent: stack });
    const tests = Array.isArray(result?.tests) ? result.tests : [];
    kit.mount('table', {
      label: clip(`Tests of the gate run (${tests.length})`, TITLE),
      columns: ['Test', 'Run', 'Verdict'],
      rows: tests.slice(0, MAX_ROWS).map((t) => fill('table-row', {
        cells: [t.name, t.test, t.verdict].map((cell) => clip(cell, CELL)),
        status: t.verdict === 'pass' ? 'pass' : 'fail',
      })),
      status_values: ['pass', 'fail'],
    }, { parent: stack });
    detail.dataset.tests = String(tests.length);
    detail.dataset.state = 'ready';
  } catch (error) {
    if (mine !== selection) return;
    kit.mount('status', { state: 'unknown', text: clip(String(error.message), SUMMARY) }, { parent: detail });
    detail.dataset.state = 'error';
  }
}

async function start() {
  try {
    const [runs, gates] = await Promise.all([get('/runs'), get('/gates')]);
    showGates(gates.gates);
    showRuns(runs.runs);
    note.textContent = `${runs.runs.length} runs and ${gates.gates.length} gate runs.`;
    main.dataset.state = 'ready';
  } catch (error) {
    note.textContent = `The page cannot read the API: ${error.message}`;
    main.dataset.state = 'error';
  }
}

start();
