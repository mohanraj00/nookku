import { expect, mock, test } from 'claude-code/testing'

// The function hooks are a display layer: each test checks that they run the nookku command and
// show its output with no change. The rules have their tests in Python (tests/).

const STARTED =
  'nookku: test 20261005-120000-ab12 started. Relay mode is on: each message goes to the entry. ' +
  'To end the test and start the evaluation, type the prompt nookku end. ' +
  'To end the test with no evaluation, run nookku end in a shell.\n'
const VIEW = 'nookku: test 20261005-120000-ab12\n──── tester ────\nHi\n──── agent ────\nHello\n'

// A fake nookku command. It answers each argv with its row of `out`, and keeps each argv in runs.
function fakes(on: any, out: Record<string, { exitCode: number; stdout: string; stderr?: string }>) {
  const runs: string[][] = []
  const status: (string | undefined)[] = []
  const opened: string[] = []
  on('process.run', async (_$: any, e: any) => {
    runs.push(e.argv)
    const r = out[e.argv[1]] ?? { exitCode: 2, stdout: '', stderr: `no fake for ${e.argv[1]}` }
    return { value: { stderr: '', ...r } }
  })
  on('ui.status', async (_$: any, e: any) => {
    status.push(e.text)
    return { value: undefined }
  })
  on('ui.open', async (_$: any, e: any) => {
    opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('session.id', async () => ({ value: 's1' }))
  return { runs, status, opened }
}

const STATUS_ON = { exitCode: 0, stdout: '{"on": true, "test": null, "text": "relay mode is on. No test runs."}\n' }
const STATUS_OFF = { exitCode: 0, stdout: '{"on": false, "test": null, "text": null}\n' }

test('/nookku start runs nookku mode and shows its output with no change', {}, async ($, on) => {
  const f = fakes(on, { mode: { exitCode: 0, stdout: STARTED }, status: STATUS_ON, view: { exitCode: 0, stdout: VIEW } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'start' } as any)
  expect(f.runs[0]).toEqual(['nookku', 'mode', 'start', '--tester-session', 's1'])
  expect(shown.text).toBe(STARTED.trimEnd())
  expect(f.status.at(-1)).toBe('relay mode is on. No test runs.')
})

test('each other word of /nookku goes to nookku mode', {}, async ($, on) => {
  const f = fakes(on, { mode: { exitCode: 0, stdout: 'Relay mode is off.\n' }, status: STATUS_OFF, view: { exitCode: 0, stdout: '' } })
  for (const args of ['end', 'off', 'on', 'status now']) {
    await $.command.run({ command: 'nookku', args } as any)
  }
  const modes = f.runs.filter(argv => argv[1] === 'mode').map(argv => argv.slice(2, -2))
  expect(modes).toEqual([['end'], ['off'], ['on'], ['status', 'now']])
  expect(f.status.at(-1)).toBe(undefined)
})

test('/nookku and /nookku status show nookku status, which names the running test', {}, async ($, on) => {
  const running = 'relay mode is on. Test 20261005-120000-ab12 runs on http://127.0.0.1:8811/.\n'
  const f = fakes(on, { status: { exitCode: 0, stdout: running }, view: { exitCode: 0, stdout: '' } })
  for (const args of ['', 'status']) {
    const shown: any = await $.command.run({ command: 'nookku', args } as any)
    expect(shown.text).toBe(running.trimEnd())
  }
  expect(f.runs.filter(argv => argv[1] === 'status' && argv.length === 2).length).toBe(2)
  expect(f.runs.some(argv => argv[1] === 'mode')).toBe(false)
})

test('if the nookku command fails, /nookku shows its error output', {}, async ($, on) => {
  fakes(on, { mode: { exitCode: 127, stdout: '', stderr: 'nookku: command not found\n' } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'on' } as any)
  expect(shown.text).toBe('nookku: command not found')
})

test('/nookku view shows the end of nookku view', {}, async ($, on) => {
  const f = fakes(on, { view: { exitCode: 0, stdout: VIEW } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'view' } as any)
  expect(f.runs).toEqual([['nookku', 'view', '--no-follow']])
  expect(shown.text).toBe(VIEW)
})

test('/nookku view shows a new turn after the record gets shorter', {}, async ($, on) => {
  // The pane keeps no count of the turns that it showed: each refresh runs nookku view again and
  // shows its output in place of the old text. So a shorter record does not hide a new turn (#113).
  const two = { exitCode: 0, stdout: VIEW + '──── tester ────\nBye\n──── agent ────\nBye now\n' }
  const out: Record<string, { exitCode: number; stdout: string }> = { view: two }
  fakes(on, out)
  await $.command.run({ command: 'nookku', args: 'view' } as any)
  const shorter = { exitCode: 0, stdout: VIEW + '──── tester ────\nTea?\n──── agent ────\nYes\n' }
  out.view = shorter
  const shown: any = await $.command.run({ command: 'nookku', args: 'view' } as any)
  expect(shown.text).toBe(shorter.stdout)
})

test('the plugin does not change a prompt or a tool call', {}, async ($, on) => {
  fakes(on, { status: STATUS_ON })
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  on('tool.call', async () => ({ result: 'ran' }))
  const prompt: any = await $.prompt.submit({ text: 'hello' })
  expect(prompt.text).toBe('hello')
  const call: any = await $.tool.call({ tool: 'Bash', command: 'ls' } as any)
  expect(call.result).toBe('ran')
})

const REFUSE = 'nookku: the relay does not send attachments. Nothing was sent.'
const IMAGE = { text: 'Is this my mug?', attachments: [{ kind: 'image' }] }

test('in relay mode, a prompt with an attachment is dropped with the text of the core', {}, async ($, on) => {
  const status = { exitCode: 0, stdout: JSON.stringify({ on: true, test: null, text: 'relay mode is on. No test runs.', attachments: REFUSE }) }
  const f = fakes(on, { status })
  const logs: string[] = []
  on('ui.log', async (_$: any, e: any) => {
    logs.push(e.text)
    return { value: undefined }
  })
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit(IMAGE as any)
  expect(result.drop).toBe(REFUSE)
  expect(logs).toEqual([REFUSE])
  expect(f.runs).toEqual([['nookku', 'status', '--json']])
})

test('with relay mode off, a prompt with an attachment goes on', {}, async ($, on) => {
  const f = fakes(on, { status: STATUS_OFF })
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit(IMAGE as any)
  expect(result.text).toBe(IMAGE.text)
  expect(f.runs.length).toBe(1)
})

test('if nookku status fails, a prompt with an attachment is dropped with the error', {}, async ($, on) => {
  fakes(on, { status: { exitCode: 127, stdout: '', stderr: 'nookku: command not found\n' } })
  on('ui.log', async () => ({ value: undefined }))
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit(IMAGE as any)
  expect(result.drop).toBe('nookku: command not found')
})

test('a prompt with no attachment does not run the nookku command', {}, async ($, on) => {
  const f = fakes(on, {})
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit({ text: 'hello' })
  expect(result.text).toBe('hello')
  expect(f.runs.length).toBe(0)
})

// The pane (#348). It shows `pane` of `nookku status --json`, and holds no secret.
const TEST = '20261005-120000-ab12'
function statusWith(pane: Record<string, unknown>) {
  const text = `relay mode is on. Test ${TEST} runs on http://127.0.0.1:8811/.`
  const data = { on: true, test: { test: TEST }, text, attachments: REFUSE, pane }
  return { exitCode: 0, stdout: JSON.stringify(data) }
}
// The lines and open of the core (page_open.pane_state).
const RUNNING = {
  test: TEST,
  state: 'running',
  turns: 2,
  page: 'test',
  lines: [`Test ${TEST}: running, 2 turns`, 'Chat page: runs. Open chat opens it in your browser.'],
  open: true,
}
const OPENED = 'The chat page opened in your browser.\n'

// Keep each toast.
function paneFakes(on: any) {
  const toasts: string[] = []
  on('ui.toast', async (_$: any, e: any) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  return { toasts }
}

async function mountPane(engine: any) {
  return engine.ui.mount({
    plugin: 'nookku',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'nookku',
    props: {
      title: 'nookku',
      isFocused: false,
      bodyColumns: 80,
      placement: 'dock',
      scroll: { offset: 0, bodyRows: 30 },
      view: {},
    },
  })
}

test('a test start opens the pane one time, with the test, its state and its turns', {}, async ($, on) => {
  mock.clock(on)
  paneFakes(on)
  const f = fakes(on, { mode: { exitCode: 0, stdout: STARTED }, status: statusWith(RUNNING), view: { exitCode: 0, stdout: VIEW } })
  await $.command.run({ command: 'nookku', args: 'start' } as any)
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  expect(f.opened).toEqual(['nookku'])
  const ui = await mountPane($)
  expect(await ui.find({ type: 'Text', text: `Test ${TEST}: running, 2 turns` })).toBeTruthy()
  expect(await ui.find({ text: 'Chat page: runs.' })).toBeTruthy()
  expect(await ui.find({ key: 'open-chat' })).toBeTruthy()
  expect(f.runs.some(argv => argv[1] === 'page')).toBe(false)
})

test('Open chat runs nookku page --open, and the pane holds no URL', {}, async ($, on) => {
  mock.clock(on)
  const p = paneFakes(on)
  const f = fakes(on, { status: statusWith(RUNNING), page: { exitCode: 0, stdout: OPENED }, view: { exitCode: 0, stdout: VIEW } })
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  const ui = await mountPane($)
  await ui.press({ key: 'open-chat' })
  expect(f.runs.filter(argv => argv[1] === 'page')).toEqual([['nookku', 'page', '--open']])
  expect(p.toasts).toEqual([OPENED.trim()])
  expect(await ui.find({ text: OPENED.trim() })).toBeTruthy()
  const shown = await ui.findAll({})
  expect(shown.some((el: any) => /https?:|\/o\/|\/p\//.test(el.text))).toBe(false)
})

test('if the chat page does not run, the pane says so and gives the command', {}, async ($, on) => {
  mock.clock(on)
  paneFakes(on)
  fakes(on, { status: statusWith({ ...RUNNING, page: 'none', lines: [RUNNING.lines[0], 'Chat page: does not run. Press Open chat to start it, or run nookku page in a separate terminal.'] }), view: { exitCode: 0, stdout: '' } })
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  const ui = await mountPane($)
  expect(await ui.find({ text: /does not run\. Press Open chat to start it, or run nookku page/ })).toBeTruthy()
  expect(await ui.find({ key: 'open-chat' })).toBeTruthy()
})

test('after the end, the pane shows the ended test and no Open chat', {}, async ($, on) => {
  mock.clock(on)
  paneFakes(on)
  fakes(on, { status: statusWith({ test: TEST, state: 'ended', turns: 3, page: 'none', lines: [`Test ${TEST}: ended, 3 turns`], open: false }), view: { exitCode: 0, stdout: '' } })
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  const ui = await mountPane($)
  expect(await ui.find({ text: `Test ${TEST}: ended, 3 turns` })).toBeTruthy()
  expect(await ui.find({ key: 'open-chat' })).toBeUndefined()
})

test('a page server of nookku page gets no Open chat', {}, async ($, on) => {
  mock.clock(on)
  paneFakes(on)
  fakes(on, { status: statusWith({ ...RUNNING, page: 'manual', lines: [RUNNING.lines[0], 'Chat page: runs from nookku page. Open it with the URL in the terminal of that command.'], open: false }), view: { exitCode: 0, stdout: '' } })
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  const ui = await mountPane($)
  expect(await ui.find({ text: /runs from nookku page/ })).toBeTruthy()
  expect(await ui.find({ key: 'open-chat' })).toBeUndefined()
})

test('while a test runs, the pane reads the state again, for the turns of the chat page', {}, async ($, on) => {
  const clock = mock.clock(on)
  paneFakes(on)
  const out: Record<string, { exitCode: number; stdout: string }> = { status: statusWith(RUNNING), view: { exitCode: 0, stdout: '' } }
  const f = fakes(on, out)
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  out.status = statusWith({ ...RUNNING, turns: 5, lines: [`Test ${TEST}: running, 5 turns`] })
  await clock.advance(5_000)
  const ui = await mountPane($)
  expect(await ui.find({ text: `Test ${TEST}: running, 5 turns` })).toBeTruthy()
  // The end stops the poll.
  out.status = statusWith({ ...RUNNING, state: 'ended', open: false })
  await clock.advance(5_000)
  const reads = () => f.runs.filter(argv => argv[1] === 'status' && argv[2] === '--json').length
  const before = reads()
  await clock.advance(15_000)
  expect(reads()).toBe(before)
})

test('a failed read of the status does not stop the poll', {}, async ($, on) => {
  const clock = mock.clock(on)
  paneFakes(on)
  const out: Record<string, { exitCode: number; stdout: string; stderr?: string }> = { status: statusWith(RUNNING), view: { exitCode: 0, stdout: '' } }
  fakes(on, out)
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  out.status = { exitCode: 1, stdout: '', stderr: 'nookku: a read failed\n' }
  await clock.advance(5_000)
  const ui = await mountPane($)
  // The pane keeps its last state and shows the error.
  expect(await ui.find({ type: 'Text', text: 'nookku: a read failed' })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: `Test ${TEST}: running, 2 turns` })).toBeTruthy()
  out.status = statusWith({ ...RUNNING, turns: 7, lines: [`Test ${TEST}: running, 7 turns`] })
  await clock.advance(5_000)
  expect(await ui.find({ type: 'Text', text: `Test ${TEST}: running, 7 turns` })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: 'nookku: a read failed' })).toBeUndefined()
})

test('after a failed first read, the poll tries again for 1 minute', {}, async ($, on) => {
  const clock = mock.clock(on)
  const out: Record<string, { exitCode: number; stdout: string; stderr?: string }> = {
    status: { exitCode: 1, stdout: '', stderr: 'nookku: a read failed\n' },
    view: { exitCode: 0, stdout: '' },
  }
  const f = fakes(on, out)
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  out.status = statusWith(RUNNING)
  await clock.advance(5_000)
  expect(f.opened).toEqual(['nookku'])
  // The last state has a running test, so a read that fails more than 12 times does not stop
  // the poll.
  out.status = { exitCode: 1, stdout: '', stderr: 'nookku: a read failed\n' }
  const reads = () => f.runs.filter(argv => argv[1] === 'status' && argv[2] === '--json').length
  let before = reads()
  for (let i = 0; i < 20; i++) await clock.advance(5_000)
  expect(reads() - before).toBe(20)
  out.status = statusWith({ ...RUNNING, state: 'ended', open: false })
  await clock.advance(5_000)
  expect(reads() - before).toBe(21)
  // With no running test in the last state, a read that always fails stops after 12 reads.
  out.status = { exitCode: 1, stdout: '', stderr: 'nookku: a read failed\n' }
  await $.command.run({ command: 'nookku', args: 'status' } as any)
  before = reads()
  for (let i = 0; i < 20; i++) await clock.advance(5_000)
  expect(reads() - before).toBe(11)
})

test('the prompt nookku start opens the pane', {}, async ($, on) => {
  mock.clock(on)
  paneFakes(on)
  const f = fakes(on, { status: statusWith(RUNNING) })
  on('prompt.submit', async () => ({ drop: STARTED }))
  await $.prompt.submit({ text: 'nookku start' })
  expect(f.opened).toEqual(['nookku'])
})
