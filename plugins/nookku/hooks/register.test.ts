import { expect, test } from 'claude-code/testing'

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
  on('process.run', async (_$: any, e: any) => {
    runs.push(e.argv)
    const r = out[e.argv[1]] ?? { exitCode: 2, stdout: '', stderr: `no fake for ${e.argv[1]}` }
    return { value: { stderr: '', ...r } }
  })
  on('ui.status', async (_$: any, e: any) => {
    status.push(e.text)
    return { value: undefined }
  })
  on('ui.open', async () => ({ value: undefined }))
  on('session.id', async () => ({ value: 's1' }))
  return { runs, status }
}

const STATUS_ON = { exitCode: 0, stdout: '{"on": true, "test": null, "text": "relay mode is on."}\n' }
const STATUS_OFF = { exitCode: 0, stdout: '{"on": false, "test": null, "text": null}\n' }

test('/nookku start runs nookku mode and shows its output with no change', {}, async ($, on) => {
  const f = fakes(on, { mode: { exitCode: 0, stdout: STARTED }, status: STATUS_ON, view: { exitCode: 0, stdout: VIEW } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'start' } as any)
  expect(f.runs[0]).toEqual(['nookku', 'mode', 'start', '--tester-session', 's1'])
  expect(shown.text).toBe(STARTED.trimEnd())
  expect(f.status.at(-1)).toBe('relay mode is on.')
})

test('each word of /nookku goes to nookku mode', {}, async ($, on) => {
  const f = fakes(on, { mode: { exitCode: 0, stdout: 'Relay mode is off.\n' }, status: STATUS_OFF, view: { exitCode: 0, stdout: '' } })
  for (const args of ['', 'status', 'end', 'off', 'on', 'other words']) {
    await $.command.run({ command: 'nookku', args } as any)
  }
  const modes = f.runs.filter(argv => argv[1] === 'mode').map(argv => argv.slice(2, -2))
  expect(modes).toEqual([[], ['status'], ['end'], ['off'], ['on'], ['other', 'words']])
  expect(f.status.at(-1)).toBe(undefined)
})

test('if the nookku command fails, /nookku shows its error output', {}, async ($, on) => {
  fakes(on, { mode: { exitCode: 127, stdout: '', stderr: 'nookku: command not found\n' } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'status' } as any)
  expect(shown.text).toBe('nookku: command not found')
})

test('/nookku view shows the end of nookku view', {}, async ($, on) => {
  const f = fakes(on, { view: { exitCode: 0, stdout: VIEW } })
  const shown: any = await $.command.run({ command: 'nookku', args: 'view' } as any)
  expect(f.runs).toEqual([['nookku', 'view', '--no-follow']])
  expect(shown.text).toBe(VIEW)
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
