// The display layer of nookku in Claude Code. The command hooks of hooks.json run `nookku hook`,
// which holds each rule: the relay, the guard, the control prompts and their texts. These function
// hooks only show what the nookku command prints: the /nookku command, the status line and the
// pane. They hold no rule. If they break, the command hooks still work (docs/contributing/adr/0001).
//
// One exception: a command hook gets only the text of a prompt, not its attachments. So in relay
// mode, the prompt hook drops a prompt with an attachment. The core gives the mode and the text.
//
// The pane holds no secret (SPEC.md section 5, "Pane"). "Open chat" runs `nookku page --open`,
// which gives a new launch URL only to the browser and prints no URL. The pane sends no message.

import { atom, read, update } from 'claude-code'
import type { Register, Timer } from 'claude-code'

import type { NookkuState, PaneData } from '../types'

const PANE = 'nookku'
// The end of a test stops the entry and copies its session files.
const CLI_TIMEOUT_MS = 180_000
// The pane shows the end of `nookku view`.
const PANE_LINES = 40
// While a test runs and the pane is open, the plugin reads the state again at this interval. A
// message of the chat page does not go through the harness, so only this read shows its turn.
const POLL_MS = 5_000
// The prompts that start, end or show a test. After one, the pane reads the state again.
const CONTROL = new Set(['nookku start', 'nookku end', 'nookku status'])

const state = atom({ plugin: 'nookku', key: 'state' } as const, { view: '' } as NookkuState)

// The timer of the poll. A hot reload starts the module again, and the next read starts a timer.
let poll: Timer | null = null
// The count of failed status reads in a row. The poll stops after MAX_FAILURES (1 minute).
const MAX_FAILURES = 12
let failures = 0

// The output of the nookku command, with no change. If the command fails, its error output.
async function runCli($: any, args: string[]): Promise<{ ok: boolean; out: string }> {
  try {
    const r = await $.process.run(['nookku', ...args], { timeoutMs: CLI_TIMEOUT_MS })
    if (r.exitCode === 0) return { ok: true, out: r.stdout ?? '' }
    return { ok: false, out: r.stdout || r.stderr || '' }
  } catch (err) {
    return { ok: false, out: String((err as Error)?.message ?? err) }
  }
}

// The status line is `text` of `nookku status --json`, and the pane shows its `pane`. The status
// line is empty if relay mode is off, or if the command fails. If a test runs that the plugin did
// not open the pane for, the plugin opens the pane.
async function showStatus($: any): Promise<void> {
  const r = await runCli($, ['status', '--json'])
  let data: any = null
  try {
    data = r.ok ? JSON.parse(r.out) : null
  } catch {
    data = null
  }
  $.ui.status(data?.text ?? undefined)
  const pane: PaneData | null = data && typeof data.pane === 'object' ? data.pane : null
  const before = await read($, state)
  const running = pane?.state === 'running' ? pane.test : null
  const open = running !== null && before.opened !== running
  // If the command fails, the pane keeps its last state and shows the error output.
  const error = data ? '' : r.out.trim()
  await update($, state, s => ({
    ...s,
    pane: data ? pane : s.pane,
    opened: open ? running : s.opened,
    note: open ? '' : s.note,
    error,
  }))
  if (open) void $.ui.open({ id: PANE, title: 'nookku' })
  // A failed read does not tell if the test runs, so the poll runs and tries again, up to
  // MAX_FAILURES reads in a row. Then the next /nookku command or control prompt tries again.
  if (pane !== null) {
    failures = 0
    setPoll($, running !== null)
  } else {
    failures += 1
    setPoll($, failures < MAX_FAILURES)
  }
}

// Read the state each POLL_MS while a test runs. Stop after the test.
function setPoll($: any, on: boolean): void {
  if (on && poll === null) {
    poll = $.clock.every(POLL_MS, () => void showStatus($))
  } else if (!on && poll !== null) {
    poll.cancel()
    poll = null
  }
}

async function refreshView($: any): Promise<void> {
  const r = await runCli($, ['view', '--no-follow'])
  await update($, state, s => ({ ...s, view: r.out.split('\n').slice(-PANE_LINES).join('\n') }))
}

// "Open chat": `nookku page --open` gives the browser a new launch URL of the chat page, and
// prints no URL. The plugin shows its output in a toast and in the pane.
async function openChat($: any): Promise<void> {
  const r = await runCli($, ['page', '--open'])
  const note = r.out.trim()
  if (note) $.ui.toast(note)
  await update($, state, s => ({ ...s, note }))
  await showStatus($)
}

async function sessionArgs($: any): Promise<string[]> {
  try {
    return ['--tester-session', await $.session.id()]
  } catch {
    return []
  }
}

// Drop a prompt with an attachment in relay mode, with the text of `nookku status --json`. If
// the command fails, the mode is not known, so drop the prompt with the error output.
async function refuseAttachments($: any, e: any, next: any): Promise<any> {
  if (!e.attachments?.length) return next(e)
  const r = await runCli($, ['status', '--json'])
  let refusal: string | null = r.out.trim()
  try {
    if (r.ok) refusal = JSON.parse(r.out).attachments ?? null
  } catch {
    // not JSON: drop the prompt with the output
  }
  if (refusal === null) return next(e)
  $.ui.log(refusal)
  return { drop: refusal }
}

// After a control prompt, the pane reads the state again: a test can start or end. A failure of
// this read does not change the result of the prompt.
async function submitPrompt($: any, e: any, next: any): Promise<any> {
  const result = await refuseAttachments($, e, next)
  if (CONTROL.has(String(e.text ?? '').trim())) {
    try {
      await showStatus($)
    } catch {
      // the pane keeps its last state
    }
  }
  return result
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'nookku',
      description: 'nookku start|end|status|on|off|view: run a test, or show the relayed turns',
    })
    await showStatus($)
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => submitPrompt($, e, next))

  // /nookku view opens the pane. /nookku and /nookku status show `nookku status`, which names
  // the running test. Each other word goes to `nookku mode`, which answers it.
  on('command.run', { command: 'nookku' }, async ($, e) => {
    const words = e.args.trim().split(/\s+/).filter(Boolean)
    if (words[0] === 'view') {
      await refreshView($)
      void $.ui.open({ id: PANE, title: 'nookku' })
      return { text: (await read($, state)).view ?? '' }
    }
    const status = words.length === 0 || (words.length === 1 && words[0] === 'status')
    const r = await runCli($, status ? ['status'] : ['mode', ...words, ...(await sessionArgs($))])
    await showStatus($)
    await refreshView($)
    return { text: r.out.trimEnd() }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const s = await read($, state)
    return (
      <Box flexDirection="column">
        {(s.pane?.lines ?? []).map(line => (
          <Text>{line}</Text>
        ))}
        {s.pane?.open && (
          <Button key="open-chat" variant="primary" onPress={() => openChat($)}>
            Open chat
          </Button>
        )}
        {s.note ? <Text dimColor>{s.note}</Text> : null}
        {s.error ? <Text dimColor>{s.error}</Text> : null}
        <Text>{s.view ?? ''}</Text>
      </Box>
    )
  })
}
