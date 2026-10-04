// verbatim-relay for Claude Code. In relay mode, each prompt that the tester types goes to the
// agent (through the tap) and never to the model. The agent's reply is shown as a transcript row,
// which the model does not receive.

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { VerbatimRelayState } from '../types'
import { blockedRow, denyPattern, isChecked, replyText, requestBody, turnRow } from './core'
import type { Options } from './core'

const PANE = 'verbatim-relay'
const TOOL = 'mcp__verbatim-relay__transcript'
const PERSON = ['composer', 'bridge', 'sdk']
// $.fs.read copies at most 4 MiB. Stop before the record reaches it.
const RECORD_LIMIT = 3.5 * 1024 * 1024

const state = atom({ plugin: 'verbatim-relay', key: 'state' } as const, {
  on: null,
  turns: [],
} as VerbatimRelayState)

async function isOn($: any, o: Options): Promise<boolean> {
  const s = await read($, state)
  return s.on ?? o.start_on
}

// The record's size, or -1 if it does not exist yet. Any other error rejects.
async function recordSize($: any, o: Options): Promise<number> {
  try {
    return (await $.fs.stat(o.record)).size
  } catch (err) {
    if (String((err as any)?.code ?? err).includes('ENOENT')) return -1
    throw err
  }
}

// $.fs has no append, so read the record and write it back whole.
async function append($: any, o: Options, line: string): Promise<void> {
  const prior = (await recordSize($, o)) < 0 ? '' : await $.fs.read(o.record)
  await $.fs.write(o.record, prior + line)
}

function showStatus($: any, relayOn: boolean): void {
  $.ui.status(relayOn ? 'verbatim-relay ON: prompts go to the agent' : undefined)
}

export const register: Register = (on, options) => {
  const o = options as unknown as Options
  const deny = denyPattern([o.tap_url, o.agent_url])

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'verbatim-relay',
      description: 'verbatim-relay on|off|status: send each prompt to the agent, not to the model',
    })
    await $.tool.register({
      name: 'transcript',
      description:
        'Read-only. The relayed test conversation so far: each tester message and the reply that the tester saw.',
      inputSchema: { type: 'object', properties: {} },
    })
    showStatus($, await isOn($, o))
    return next(e)
  })

  on('command.run', { command: 'verbatim-relay' }, async ($, e) => {
    const arg = e.args.trim()
    if (arg === 'on' || arg === 'off') {
      await update($, state, s => ({ ...s, on: arg === 'on' }))
      showStatus($, arg === 'on')
      if (arg === 'on') void $.ui.open({ id: PANE, title: 'verbatim-relay' })
    } else if (arg !== '' && arg !== 'status') {
      return { text: 'Usage: /verbatim-relay on|off|status' }
    }
    const relayOn = await isOn($, o)
    return {
      text: `Relay mode is ${relayOn ? 'on' : 'off'}. Tap: ${o.tap_url}. Record: ${o.record}.`,
    }
  })

  on('prompt.submit', async ($, e, next) => {
    const fromPerson = !e.origin || PERSON.includes(e.origin.kind)
    if (!fromPerson || !(await isOn($, o))) return next(e)
    if (e.attachments?.length) {
      $.ui.log('verbatim-relay: v0.1 does not relay attachments. Nothing was sent.')
      return { drop: 'verbatim-relay: nothing was sent' }
    }
    if ((await recordSize($, o)) > RECORD_LIMIT) {
      $.ui.log(`verbatim-relay: the record ${o.record} is full. Move it, then send again. Nothing was sent.`)
      return { drop: 'verbatim-relay: nothing was sent' }
    }

    const said = e.text
    const s = await read($, state)
    let shown: string
    let ok = false
    try {
      const res = await $.http.fetch(o.tap_url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody(o, said, s.turns),
      })
      if (res.ok) {
        try {
          shown = replyText(o, res.text)
          ok = true
        } catch (err) {
          shown = `verbatim-relay: cannot read the reply: ${(err as Error).message}`
        }
      } else {
        shown = `verbatim-relay: the agent returned HTTP ${res.status}:\n${res.text}`
      }
    } catch (err) {
      shown = `verbatim-relay: cannot reach the tap at ${o.tap_url}: ${(err as Error).message}`
    }

    $.ui.log(shown)
    await update($, state, st => ({ ...st, turns: [...st.turns, { said, shown, ok }] }))
    try {
      await append($, o, await turnRow(said, shown, ok))
    } catch (err) {
      $.ui.log(`verbatim-relay: cannot write the record ${o.record}: ${(err as Error).message}`)
    }
    return { drop: 'verbatim-relay: relayed to the agent' }
  })

  on('tool.call', { tool: TOOL }, async $ => {
    const s = await read($, state)
    return { result: JSON.stringify(s.turns, null, 1) }
  })

  // The model may read the conversation. It must not take part in it.
  on('tool.call', async ($, e, next) => {
    if (deny && isChecked(e.tool) && deny.test(JSON.stringify(e))) {
      try {
        await append($, o, blockedRow(e.tool, JSON.stringify(e).slice(0, 300)))
      } catch {
        // The deny holds even if the record cannot take the row.
      }
      return {
        deny: 'verbatim-relay: only the tester talks to the agent. Use the transcript tool to read the conversation.',
      }
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, state)
    return (
      <Box flexDirection="column">
        {s.turns.length === 0 && <Text dimColor>No relayed turns yet. Type /verbatim-relay on, then a message.</Text>}
        {s.turns.slice(-6).map((t, i) => (
          <Box key={String(i)} flexDirection="column">
            <Text bold>tester:</Text>
            <Text>{t.said}</Text>
            <Text bold color={t.ok ? undefined : 'red'}>
              agent:
            </Text>
            <Text>{t.shown ?? ''}</Text>
          </Box>
        ))}
      </Box>
    )
  })
}
