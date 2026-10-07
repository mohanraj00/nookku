// verbatim-relay for Claude Code. In relay mode, each prompt that the tester types goes to the
// agent (through the tap) and never to the model. The agent's reply is shown as a transcript row,
// which the model does not receive.
//
// If .verbatim-relay/config.json has an entry, relay mode is a test (SPEC.md section 7): the
// verbatim-relay command starts the entry through the tap, and each prompt goes to that test.
// Relay mode is then the file .verbatim-relay/mode, which `start` and `end` write. It survives a
// reload of the plugin, so a running test never loses relay mode.

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { VerbatimRelayState, VerbatimRelayTurn } from '../types'
import { blockedRow, contractBody, commandOf, contractShown, denyPattern, entryNames, isChecked, namesEntry, replyText, requestBody, toolReadsOnly, touchesRecords, touchesTestFiles, turnRow } from './core'
import type { Current, Options } from './core'

const PANE = 'verbatim-relay'
const TOOL = 'mcp__verbatim-relay__transcript'
const PERSON = ['composer', 'bridge', 'sdk']
const CONFIG = '.verbatim-relay/config.json'
const CURRENT = '.verbatim-relay/current.json'
const MODE = '.verbatim-relay/mode'
const TEST_FILES = /\.verbatim-relay/
const RECORDS_REASON = 'verbatim-relay: the records of a test do not change. Write only report.md. A command that names .verbatim-relay may only read.'
// Prompts that run the test and are never relayed (SPEC.md section 5).
const CONTROL = ['verbatim-relay start', 'verbatim-relay end', 'verbatim-relay status']
// $.fs.read copies at most 4 MiB. Stop before the record reaches it.
const RECORD_LIMIT = 3.5 * 1024 * 1024
// The end of a test stops the entry and copies its session files.
const CLI_TIMEOUT_MS = 180_000

const state = atom({ plugin: 'verbatim-relay', key: 'state' } as const, {
  on: null,
  turns: [],
  test: null,
} as VerbatimRelayState)

async function isOn($: any, o: Options): Promise<boolean> {
  if (await hasEntry($)) return modeOn($)
  const s = await read($, state)
  return s.on ?? o.start_on
}

async function modeOn($: any): Promise<boolean> {
  try {
    if ((await fileSize($, MODE)) < 0) return false
    return String(await $.fs.read(MODE)).trim() === 'on'
  } catch {
    return false
  }
}

// A file's size, or -1 if it does not exist yet. Any other error rejects.
async function fileSize($: any, path: string): Promise<number> {
  try {
    return (await $.fs.stat(path)).size
  } catch (err) {
    if (String((err as any)?.code ?? err).includes('ENOENT')) return -1
    throw err
  }
}

// A JSON file, or null if it does not exist or is not JSON.
async function readJson($: any, path: string): Promise<any> {
  try {
    if ((await fileSize($, path)) < 0) return null
    return JSON.parse(String(await $.fs.read(path)))
  } catch {
    return null
  }
}

async function hasEntry($: any): Promise<boolean> {
  const config = await readJson($, CONFIG)
  return Array.isArray(config?.entry) && config.entry.length > 0
}

async function currentTest($: any): Promise<Current | null> {
  const cur = await readJson($, CURRENT)
  return cur && typeof cur.tap_url === 'string' && typeof cur.dir === 'string' ? (cur as Current) : null
}

// $.fs has no append, so read the record and write it back whole.
async function append($: any, path: string, line: string): Promise<void> {
  const prior = (await fileSize($, path)) < 0 ? '' : await $.fs.read(path)
  await $.fs.write(path, prior + line)
}

// The turns of a record, of one session or (with null) of all sessions. The record outlives the
// plugin's state, so a resumed session keeps its transcript and its history.
async function recordTurns($: any, path: string, session: string | null): Promise<VerbatimRelayTurn[]> {
  if ((await fileSize($, path)) < 0) return []
  const turns: VerbatimRelayTurn[] = []
  for (const line of String(await $.fs.read(path)).split('\n')) {
    if (!line) continue
    const row = JSON.parse(line)
    if (row.type === 'turn' && (session === null || row.session === session)) {
      turns.push({ said: row.said, shown: row.shown, ok: row.ok === true })
    }
  }
  return turns
}

function showStatus($: any, relayOn: boolean): void {
  $.ui.status(relayOn ? 'verbatim-relay ON: prompts go to the agent' : undefined)
}

// Run the verbatim-relay command. Resolve its exit code and its output. With exact, the output of
// a command that passes is its stdout with no change.
async function runCli($: any, o: Options, args: string[], exact = false): Promise<{ ok: boolean; out: string }> {
  try {
    const r = await $.process.run([o.cli, ...args], { timeoutMs: CLI_TIMEOUT_MS })
    if (exact && r.exitCode === 0) return { ok: true, out: r.stdout ?? '' }
    return { ok: r.exitCode === 0, out: (r.stdout || r.stderr || '').trim() }
  } catch (err) {
    return { ok: false, out: `cannot run '${o.cli}': ${(err as Error).message}` }
  }
}

async function startTest($: any, o: Options): Promise<string> {
  const r = await runCli($, o, ['start', '--json', '--tester-session', await $.session.id()])
  let cur: any = null
  try {
    cur = JSON.parse(r.out)
  } catch {
    // not JSON: the command failed before it could answer
  }
  if (!r.ok || !cur?.test) return `The test did not start: ${cur?.error ?? r.out}`
  await update($, state, s => ({ ...s, on: true, turns: [], test: cur.dir }))
  showStatus($, true)
  void $.ui.open({ id: PANE, title: 'verbatim-relay' })
  return `Test ${cur.test} started. Relay mode is on. Type /verbatim-relay end to end it.`
}

async function endTest($: any, o: Options): Promise<string> {
  await update($, state, s => ({ ...s, on: false }))
  showStatus($, false)
  const r = await runCli($, o, ['end'])
  return r.ok ? `Relay mode is off.\n${r.out}` : `The test did not end: ${r.out}`
}

// End the test for the control prompt `verbatim-relay end`. Resolve the text to show and the
// evaluation prompt, or null if the test needs no evaluation (SPEC.md section 9).
async function endForEvaluation($: any, o: Options): Promise<{ text: string; evaluation: string | null }> {
  await update($, state, s => ({ ...s, on: false }))
  showStatus($, false)
  const r = await runCli($, o, ['end', '--evaluation'])
  try {
    const j = JSON.parse(r.out)
    if (r.ok) return { text: `Relay mode is off.\n${j.text}`, evaluation: j.evaluation ?? null }
  } catch {
    // not JSON: the command failed before it could answer
  }
  return { text: `The test did not end: ${r.out}`, evaluation: null }
}

async function statusText($: any, o: Options): Promise<string> {
  const cur = await currentTest($)
  const test = cur ? ` Test ${cur.test} runs on ${cur.tap_url}.` : ' No test runs.'
  return `Relay mode is ${(await isOn($, o)) ? 'on' : 'off'}.${test}`
}

// Run a control prompt. Resolve the answer of the prompt.submit hook.
async function runControl($: any, o: Options, e: any, next: any, control: string): Promise<any> {
  if (control === 'verbatim-relay start') {
    $.ui.log(`verbatim-relay: ${await startTest($, o)}`)
    return { drop: 'verbatim-relay: the test command ran' }
  }
  if (control === 'verbatim-relay status') {
    $.ui.log(`verbatim-relay: ${await statusText($, o)}`)
    return { drop: 'verbatim-relay: the test command ran' }
  }
  const { text, evaluation } = await endForEvaluation($, o)
  $.ui.log(`verbatim-relay: ${text}`)
  if (evaluation === null) return { drop: 'verbatim-relay: the test command ran' }
  // The prompt goes on to the model, which evaluates the test.
  return next({ ...e, context: [...(e.context ?? []), `${text}\n\n${evaluation}`] })
}

// Send one prompt to the running test. Resolve the text to show, whether it is the reply, and the
// record that takes the turn.
async function relayToTest($: any, cur: Current, said: string): Promise<{ shown: string; ok: boolean; record: string }> {
  const record = `${cur.dir}/relay.jsonl`
  const id = crypto.randomUUID()
  const body = contractBody(id, cur.test, said, await recordTurns($, record, null))
  try {
    const res = await $.http.fetch(cur.tap_url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    return { ...contractShown(res.status, res.text, id), record }
  } catch (err) {
    return { shown: `verbatim-relay: cannot reach the tap at ${cur.tap_url}: ${(err as Error).message}`, ok: false, record }
  }
}

// Send one prompt to the tap of SPEC.md section 4.1, with the configured adapter.
async function relayToTap($: any, o: Options, said: string, session: string): Promise<{ shown: string; ok: boolean; record: string }> {
  const past = await recordTurns($, o.record, session)
  try {
    const res = await $.http.fetch(o.tap_url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: requestBody(o, said, past),
    })
    if (!res.ok) return { shown: `verbatim-relay: the agent returned HTTP ${res.status}:\n${res.text}`, ok: false, record: o.record }
    try {
      return { shown: replyText(o, res.text), ok: true, record: o.record }
    } catch (err) {
      return { shown: `verbatim-relay: cannot read the reply: ${(err as Error).message}`, ok: false, record: o.record }
    }
  } catch (err) {
    return { shown: `verbatim-relay: cannot reach the tap at ${o.tap_url}: ${(err as Error).message}`, ok: false, record: o.record }
  }
}

// The name and the message of a thrown value, as the hook kit shows them.
function failure(err: unknown): string {
  const message = (err as any)?.message
  return typeof message === 'string' ? `${(err as any)?.name ?? 'Error'}: ${message}` : String(err)
}

// Why the engine stopped a hook (its HookFailure): it threw, it returned a value that the engine
// refuses, or it ran past its time budget.
function hookFailure(f: any): string {
  return `${f?.kind ?? 'throw'}: ${f?.message ?? 'no message'}`
}

// A failed relay path blocks the prompt. If the handler rejects, the engine skips it and gives
// the prompt to the model, so the handler must never reject in relay mode.
function blockFailed($: any, detail: string): any {
  try {
    $.ui.log(`verbatim-relay: the hook failed (${detail}). Nothing reached the model.`)
  } catch {
    // The block holds even if the log fails.
  }
  return { drop: 'verbatim-relay: nothing reached the model' }
}

// Relay mode is on, or a test runs. This check does not hide errors: if it cannot read a file
// of the mode, it assumes that relay mode is on.
async function guardOn($: any, o: Options): Promise<boolean> {
  try {
    if ((await fileSize($, CURRENT)) >= 0) return true
    const config = (await fileSize($, CONFIG)) < 0 ? null : JSON.parse(String(await $.fs.read(CONFIG)))
    if (!(Array.isArray(config?.entry) && config.entry.length > 0)) {
      const s = await read($, state)
      return s.on ?? o.start_on
    }
    if ((await fileSize($, MODE)) < 0) return false
    return String(await $.fs.read(MODE)).trim() === 'on'
  } catch {
    return true
  }
}

// The .catch handler of prompt.submit. The engine calls it when the hook throws, returns a value
// that the engine refuses, or runs past its time budget. A stalled file or state call can cause
// the failure, so this handler makes no such call. The hook passes a prompt to the model only
// after it knows that relay mode is off, so here the mode is on or unknown. The handler blocks
// each prompt from the person. A prompt from another origin goes on, because the hook is absent.
async function promptFailed($: any, o: Options, e: any, next: any): Promise<any> {
  // If the hook already gave the prompt to the model, that result stands.
  if (next.called) return next(e)
  const fromPerson = !e.origin || PERSON.includes(e.origin.kind)
  if (fromPerson) return blockFailed($, hookFailure(next.error))
  return undefined
}

// The .catch handler of a tool.call hook. It makes no file or state call, for the same reason.
// With relay mode off, the hooks let a call go on and do not throw, so here the mode is on or
// unknown. The handler denies the call.
async function toolFailed($: any, o: Options, e: any, next: any): Promise<any> {
  // If the hook already let the call run, that result stands.
  if (next.called) return next(e)
  return { deny: `verbatim-relay: the hook failed (${hookFailure(next.error)}). The tool call did not run.` }
}

// Send one prompt in relay mode. Resolve the answer of the prompt.submit hook. It never calls
// next, so the prompt never reaches the model.
async function relayPrompt($: any, o: Options, e: any): Promise<any> {
  if (e.attachments?.length) {
    $.ui.log('verbatim-relay: the relay does not send attachments. Nothing was sent.')
    return { drop: 'verbatim-relay: nothing was sent' }
  }
  const cur = await currentTest($)
  if (!cur && (await hasEntry($))) {
    $.ui.log('verbatim-relay: relay mode is on, but no test runs. Type /verbatim-relay start. Nothing was sent.')
    return { drop: 'verbatim-relay: nothing was sent' }
  }
  const recordPath = cur ? `${cur.dir}/relay.jsonl` : o.record
  if ((await fileSize($, recordPath)) > RECORD_LIMIT) {
    $.ui.log(`verbatim-relay: the record ${recordPath} is full. Move it, then send again. Nothing was sent.`)
    return { drop: 'verbatim-relay: nothing was sent' }
  }

  const said = e.text
  const session = await $.session.id()
  const { shown, ok, record } = cur ? await relayToTest($, cur, said) : await relayToTap($, o, said, session)
  $.ui.log(shown)
  await update($, state, st => ({ ...st, turns: [...st.turns, { said, shown, ok }] }))
  try {
    await append($, record, await turnRow(said, shown, ok, session))
  } catch (err) {
    $.ui.log(`verbatim-relay: cannot write the record ${record}: ${(err as Error).message}`)
  }
  return { drop: 'verbatim-relay: relayed to the agent' }
}

// The deny of a model tool call, or null if the call may run. It never calls next.
async function guardTool($: any, o: Options, e: any): Promise<{ deny: string } | null> {
  const cur = await currentTest($)
  const input = JSON.stringify(e)
  const deny = denyPattern([o.tap_url, o.agent_url, cur?.tap_url ?? ''])
  const toTap = deny !== null && isChecked(e.tool) && deny.test(input)
  if (toTap || (cur !== null && touchesTestFiles(e.tool, input))) {
    try {
      await append($, cur ? `${cur.dir}/relay.jsonl` : o.record, blockedRow(e.tool, input.slice(0, 300)))
    } catch {
      // The deny holds even if the record cannot take the row.
    }
    return {
      deny: 'verbatim-relay: only the tester talks to the agent, and the test files do not change during a test. Use the transcript tool to read the conversation.',
    }
  }
  const reads = toolReadsOnly(e.tool, e)
  if (cur === null && (touchesRecords(e.tool, input) || (isChecked(e.tool) && TEST_FILES.test(input) && !reads))) {
    const s = await read($, state)
    try {
      await append($, s.test ? `${s.test}/denied.jsonl` : o.record, blockedRow(e.tool, input.slice(0, 300)))
    } catch {
      // The deny holds even if the record cannot take the row.
    }
    return { deny: RECORDS_REASON }
  }
  const entry = cur !== null && isChecked(e.tool) && !reads ? (await readJson($, CONFIG))?.entry : null
  if (Array.isArray(entry) && namesEntry(input, entryNames(entry.map(String)), commandOf(e.tool, e))) {
    try {
      await append($, `${cur!.dir}/relay.jsonl`, blockedRow(e.tool, input.slice(0, 300)))
    } catch {
      // The deny holds even if the record cannot take the row.
    }
    return { deny: 'verbatim-relay: during a test, only the tap runs the entry.' }
  }
  return null
}

export const register: Register = (on, options) => {
  const o = options as unknown as Options

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'verbatim-relay',
      description: 'verbatim-relay start|end|status (on|off): send each prompt to the agent, not to the model',
    })
    await $.tool.register({
      name: 'transcript',
      description:
        'Read-only. The exact test conversation: each message that the tester typed and the reply that the agent sent. Use it to evaluate the agent. With trace: true, each turn of the latest test as the app got it, with the model items of the app (its messages, tool calls and commands).',
      inputSchema: {
        type: 'object',
        properties: { trace: { type: 'boolean', description: 'Show the trace of the latest test under each turn.' } },
      },
    })
    showStatus($, await isOn($, o))
    return next(e)
  })

  on('command.run', { command: 'verbatim-relay' }, async ($, e) => {
    const arg = e.args.trim()
    const known = ['', 'status', 'on', 'off', 'start', 'end']
    if (!known.includes(arg)) return { text: 'Usage: /verbatim-relay start|end|status (on and off are the same as start and end)' }
    if (await hasEntry($)) {
      if (arg === 'start' || arg === 'on') return { text: await startTest($, o) }
      if (arg === 'end' || arg === 'off') return { text: await endTest($, o) }
      return { text: await statusText($, o) }
    }
    if (arg === 'start' || arg === 'end') {
      return { text: `A test needs an entry in ${CONFIG}. Without one, use /verbatim-relay on|off.` }
    }
    if (arg === 'on' || arg === 'off') {
      await update($, state, s => ({ ...s, on: arg === 'on' }))
      showStatus($, arg === 'on')
      if (arg === 'on') void $.ui.open({ id: PANE, title: 'verbatim-relay' })
    }
    const relayOn = await isOn($, o)
    return {
      text: `Relay mode is ${relayOn ? 'on' : 'off'}. Tap: ${o.tap_url}. Record: ${o.record}.`,
    }
  })

  on('prompt.submit', async ($, e, next) => {
    const fromPerson = !e.origin || PERSON.includes(e.origin.kind)
    const control = e.text.trim()
    if (fromPerson && CONTROL.includes(control) && (await hasEntry($))) return runControl($, o, e, next, control)
    if (!fromPerson || !(await isOn($, o))) return next(e)
    try {
      return await relayPrompt($, o, e)
    } catch (err) {
      return blockFailed($, failure(err))
    }
  }).catch(($, e, next) => promptFailed($, o, e, next))

  // The verbatim-relay command renders the transcript, so the plugin and the hook kit give the
  // model the same text (SPEC.md section 5).
  on('tool.call', { tool: TOOL }, async ($, e) => {
    const s = await read($, state)
    const args = (e as any).trace === true
      ? ['transcript', '--trace']
      : s.test
        ? ['transcript', '--test', s.test.split('/').filter(Boolean).pop() ?? '']
        : ['transcript', '--record', o.record, '--session', await $.session.id()]
    const r = await runCli($, o, args, true)
    return { result: r.out }
  }).catch(($, e, next) => toolFailed($, o, e, next))

  // The model may read the conversation. It must not take part in it, and during a test it must
  // not change the entry or the test files.
  on('tool.call', async ($, e, next) => {
    let denied: { deny: string } | null
    try {
      denied = await guardTool($, o, e)
    } catch (err) {
      // A failed guard denies the call in relay mode or during a test, as the hook kit does.
      if (!(await guardOn($, o))) return next(e)
      denied = { deny: `verbatim-relay: the hook failed (${failure(err)}). The tool call did not run.` }
    }
    return denied ?? next(e)
  }).catch(($, e, next) => toolFailed($, o, e, next))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, state)
    return (
      <Box flexDirection="column">
        {s.turns.length === 0 && <Text dimColor>No relayed turns yet. Type /verbatim-relay start, then a message.</Text>}
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
