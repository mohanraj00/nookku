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
}

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

// Tools that can reach the network. File tools are left alone: a file that names the agent's
// address is not a call to the agent.
export function isNetworkTool(tool: string): boolean {
  return ['Bash', 'PowerShell', 'WebFetch'].includes(tool) || (tool.startsWith('mcp__') && !tool.startsWith('mcp__verbatim-relay__'))
}

export async function turnRow(said: string, shown: string | null): Promise<string> {
  const row = {
    v: '0.1',
    type: 'turn',
    ts: Date.now() / 1000,
    harness: HARNESS,
    said,
    said_sha256: await sha256(said),
    shown,
    shown_sha256: await sha256(shown),
  }
  return JSON.stringify(row) + '\n'
}

export function blockedRow(tool: string, detail: string): string {
  const row = { v: '0.1', type: 'blocked_call', ts: Date.now() / 1000, harness: HARNESS, tool, detail }
  return JSON.stringify(row) + '\n'
}
