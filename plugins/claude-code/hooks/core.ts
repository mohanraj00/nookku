// Pure parts of the plugin: requests, replies, record rows and the deny pattern (SPEC.md).

import type { VerbatimRelayTurn } from '../types'

export type Options = {
  tap_url: string
  agent_url: string
  adapter: string
  message_field: string
  reply_field: string
  openai_model: string
  record: string
  start_on: boolean
  cli: string
}

// The running test, from .verbatim-relay/current.json (SPEC.md section 7.2).
export type Current = { test: string; dir: string; tap_url: string; pid: number }

export const HARNESS = 'claude-code'

export async function sha256(text: string | null): Promise<string | null> {
  if (text === null) return null
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
}

export function pick(data: unknown, path: string): unknown {
  for (const key of path.split('.')) {
    if (Array.isArray(data) && /^\d+$/.test(key) && Number(key) < data.length) data = data[Number(key)]
    else if (data !== null && typeof data === 'object' && !Array.isArray(data) && key in data)
      data = (data as Record<string, unknown>)[key]
    else throw new Error(`no value at '${path}'`)
  }
  return data
}

function nest(path: string, value: unknown): unknown {
  return path
    .split('.')
    .reverse()
    .reduce<unknown>((inner, key) => ({ [key]: inner }), value)
}

// The request body for one tester message. The openai adapter sends the whole conversation.
export function requestBody(o: Options, said: string, turns: readonly VerbatimRelayTurn[]): string {
  if (o.adapter === 'openai') {
    const messages: { role: string; content: string }[] = []
    for (const t of turns) {
      if (!t.ok || t.shown === null) continue
      messages.push({ role: 'user', content: t.said }, { role: 'assistant', content: t.shown })
    }
    messages.push({ role: 'user', content: said })
    const body: Record<string, unknown> = { messages, stream: false }
    if (o.openai_model) body.model = o.openai_model
    return JSON.stringify(body)
  }
  return JSON.stringify(nest(o.message_field, said))
}

// The agent contract (SPEC.md section 6). The tap forwards this body to the entry without change.
export function contractBody(id: string, test: string, said: string, turns: readonly VerbatimRelayTurn[]): string {
  const history = turns.filter(t => t.ok && t.shown !== null).map(t => ({ message: t.said, reply: t.shown }))
  return JSON.stringify({ v: 1, id, session: test, message: said, history })
}

// What the tester sees for one tap response, and whether it is the agent's reply.
export function contractShown(status: number, body: string, id: string): { shown: string; ok: boolean } {
  let data: any = null
  try {
    data = JSON.parse(body)
  } catch {
    // not JSON: show the body as it came
  }
  const mine = data !== null && typeof data === 'object' && data.v === 1 && data.id === id
  if (status === 200) {
    if (mine && typeof data.reply === 'string' && data.error === undefined) return { shown: data.reply, ok: true }
    return { shown: `verbatim-relay: cannot read the reply: ${body}`, ok: false }
  }
  if (status === 500 && mine && typeof data.error === 'string') {
    return { shown: `verbatim-relay: the agent sent an error:\n${data.error}`, ok: false }
  }
  const error = data !== null && typeof data?.error === 'string' ? data.error : body
  return { shown: `verbatim-relay: HTTP ${status}: ${error}`, ok: false }
}

export function replyText(o: Options, body: string): string {
  const path = o.adapter === 'openai' ? 'choices.0.message.content' : o.reply_field
  let data: unknown
  try {
    data = JSON.parse(body)
  } catch {
    throw new Error('the response body is not JSON')
  }
  const value = pick(data, path)
  if (typeof value !== 'string') throw new Error(`the value at '${path}' is not a string`)
  return value
}

const LOOPBACK = ['127.0.0.1', 'localhost', '0.0.0.0', '[::1]']

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// A pattern for the spellings of each URL's host and port. Best effort: the audit is the proof.
export function denyPattern(urls: readonly string[]): RegExp | null {
  const parts: string[] = []
  for (const raw of urls) {
    if (!raw) continue
    const url = new URL(raw)
    const port = url.port || (url.protocol === 'https:' ? '443' : '80')
    const hosts = LOOPBACK.includes(url.hostname) || url.hostname === '[::1]' ? LOOPBACK : [url.hostname]
    for (const host of hosts) {
      parts.push(`${escape(host)}:${port}(?!\\d)`)
      if (!url.port) parts.push(`${escape(host)}(?![\\w.:-])`)
    }
  }
  return parts.length ? new RegExp(parts.join('|'), 'i') : null
}

// Tools that only read, write or search files (SPEC.md section 5). Every other tool is checked,
// so a tool that the plugin does not know is denied when its input names the tap or the agent.
const FILE_TOOLS = ['Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Glob', 'Grep', 'LS', 'TodoWrite']
const WRITE_TOOLS = ['Write', 'Edit', 'MultiEdit', 'NotebookEdit']
const TEST_FILES = /\.verbatim-relay/

export function isChecked(tool: string): boolean {
  return !FILE_TOOLS.includes(tool) && !tool.startsWith('mcp__verbatim-relay__')
}

// During a test, the model must not change the entry or the test files (SPEC.md section 5).
export function touchesTestFiles(tool: string, input: string): boolean {
  if (!TEST_FILES.test(input)) return false
  return WRITE_TOOLS.includes(tool) || isChecked(tool)
}

export async function turnRow(said: string, shown: string | null, ok: boolean, session: string): Promise<string> {
  const row = {
    v: '0.2',
    type: 'turn',
    ts: Date.now() / 1000,
    harness: HARNESS,
    said,
    said_sha256: await sha256(said),
    shown,
    shown_sha256: await sha256(shown),
    ok,
    session,
  }
  return JSON.stringify(row) + '\n'
}

export function blockedRow(tool: string, detail: string): string {
  const row = { v: '0.2', type: 'blocked_call', ts: Date.now() / 1000, harness: HARNESS, tool, detail }
  return JSON.stringify(row) + '\n'
}
