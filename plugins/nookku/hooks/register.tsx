// The display layer of nookku in Claude Code. The command hooks of hooks.json run `nookku hook`,
// which holds each rule: the relay, the guard, the control prompts and their texts. These function
// hooks only show what the nookku command prints: the /nookku command, the status line and the
// pane. They hold no rule. If they break, the command hooks still work (docs/adr/0001).

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { NookkuState } from '../types'

const PANE = 'nookku'
// The end of a test stops the entry and copies its session files.
const CLI_TIMEOUT_MS = 180_000
// The pane shows the end of `nookku view`.
const PANE_LINES = 40

const state = atom({ plugin: 'nookku', key: 'state' } as const, { view: '' } as NookkuState)

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

// The status line is the text of `nookku status --json`. It is empty if relay mode is off, or if
// the command fails.
async function showStatus($: any): Promise<void> {
  const r = await runCli($, ['status', '--json'])
  let text: string | undefined
  try {
    text = r.ok ? (JSON.parse(r.out).text ?? undefined) : undefined
  } catch {
    text = undefined
  }
  $.ui.status(text)
}

async function refreshView($: any): Promise<void> {
  const r = await runCli($, ['view', '--no-follow'])
  await update($, state, s => ({ ...s, view: r.out.split('\n').slice(-PANE_LINES).join('\n') }))
}

async function sessionArgs($: any): Promise<string[]> {
  try {
    return ['--tester-session', await $.session.id()]
  } catch {
    return []
  }
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

  // /nookku view opens the pane. Each other word goes to `nookku mode`, which answers it.
  on('command.run', { command: 'nookku' }, async ($, e) => {
    const words = e.args.trim().split(/\s+/).filter(Boolean)
    if (words[0] === 'view') {
      await refreshView($)
      void $.ui.open({ id: PANE, title: 'nookku' })
      return { text: (await read($, state)).view ?? '' }
    }
    const r = await runCli($, ['mode', ...words, ...(await sessionArgs($))])
    await showStatus($)
    await refreshView($)
    return { text: r.out.trimEnd() }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, state)
    return (
      <Box flexDirection="column">
        <Text>{s.view ?? ''}</Text>
      </Box>
    )
  })
}
