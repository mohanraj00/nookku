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
export type Current = { test: string; dir: string; tap_url: string; pid: number; pid_start: string }

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
// A line with both 'reply' and 'error' is not a contract line, also if one is null (SPEC.md section 6).
// A lone surrogate is not a Unicode scalar value (SPEC.md section 2). The tap returns 502 for it.
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/

export function contractShown(status: number, body: string, id: string): { shown: string; ok: boolean } {
  let data: any = null
  try {
    data = JSON.parse(body)
  } catch {
    // not JSON: show the body as it came
  }
  const mine = data !== null && typeof data === 'object' && data.v === 1 && data.id === id
  if (status === 200) {
    if (mine && typeof data.reply === 'string' && data.error === undefined && !LONE_SURROGATE.test(data.reply)) return { shown: data.reply, ok: true }
    return { shown: `verbatim-relay: cannot read the reply: ${body}`, ok: false }
  }
  if (status === 500 && mine && typeof data.error === 'string' && data.reply === undefined && !LONE_SURROGATE.test(data.error)) {
    return { shown: `verbatim-relay: the agent sent an error:\n${data.error}`, ok: false }
  }
  const error = data !== null && typeof data?.error === 'string' ? data.error : body
  return { shown: `verbatim-relay: HTTP ${status}: ${error}`, ok: false }
}

// True if a Content-Type is text/event-stream (SPEC.md section 4.1).
export function isStream(contentType: string | undefined): boolean {
  return (contentType ?? '').split(';')[0].trim().toLowerCase() === 'text/event-stream'
}

// The name and the data of each event of an SSE body, in order. The rules are those of the WHATWG
// HTML standard. The last event does not need a blank line after it.
export function sseEvents(body: string): { name: string; data: string }[] {
  const events: { name: string; data: string }[] = []
  let name = ''
  let data: string[] = []
  for (const line of [...body.replace(/^﻿/, '').split(/\r\n|\r|\n/), '']) {
    if (line === '') {
      if (data.length) events.push({ name: name || 'message', data: data.join('\n') })
      name = ''
      data = []
    } else if (!line.startsWith(':')) {
      const i = line.indexOf(':')
      const key = i < 0 ? line : line.slice(0, i)
      const raw = i < 0 ? '' : line.slice(i + 1)
      const value = raw.startsWith(' ') ? raw.slice(1) : raw
      if (key === 'data') data.push(value)
      else if (key === 'event') name = value
    }
  }
  return events
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

// The reply of an openai stream: the joined choices[0].delta.content texts (SPEC.md section 4.1).
// A stream with no `data: [DONE]`, an event after it, an error or a malformed chunk is an error.
export function streamText(body: string): string {
  const parts: string[] = []
  let done = false
  for (const { name, data } of sseEvents(body)) {
    if (done) throw new Error('the stream has an event after data: [DONE]')
    if (data === '[DONE]') {
      done = true
      continue
    }
    if (name === 'error') throw new Error(`the agent sent an error event: ${data}`)
    let chunk: unknown
    try {
      chunk = JSON.parse(data)
    } catch {
      throw new Error(`a chunk is not JSON: ${data.slice(0, 80)}`)
    }
    if (!isObject(chunk)) throw new Error(`a chunk is not a JSON object: ${data.slice(0, 80)}`)
    if (chunk.error !== undefined && chunk.error !== null) throw new Error(`the agent sent an error: ${JSON.stringify(chunk.error)}`)
    const choices = 'choices' in chunk ? chunk.choices : []
    if (!Array.isArray(choices)) throw new Error("the 'choices' of a chunk is not a list")
    for (const choice of choices) {
      const delta = isObject(choice) ? ('delta' in choice ? choice.delta : {}) : null
      if (!isObject(choice) || !isObject(delta)) throw new Error("a choice of a chunk has no 'delta' object")
      if (('index' in choice ? choice.index : 0) !== 0) continue
      const content = delta.content ?? null
      if (content !== null && typeof content !== 'string') throw new Error("the 'delta.content' of a chunk is not a string")
      if (content !== null) parts.push(content)
    }
  }
  if (!done) throw new Error('the stream ended before data: [DONE]')
  if (!parts.length) throw new Error("no chunk of the stream has a 'delta.content' text")
  const text = parts.join('')
  // A lone surrogate is not a Unicode scalar value (SPEC.md section 2).
  if (/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(text)) throw new Error('the stream reply has a lone surrogate')
  return text
}

// The reply in a tap response. The relay shows a streamed reply only when it is complete.
export function replyText(o: Options, body: string, contentType = ''): string {
  if (isStream(contentType)) {
    if (o.adapter !== 'openai') throw new Error('the json adapter does not read a streamed response')
    return streamText(body)
  }
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

// After a test, the model may write report.md in a test folder, and no other file of it
// (SPEC.md section 9).
const TEST_FOLDER_FILE = /\.verbatim-relay\/tests\/[^/\s"']+\/([^\s"'\\]*)/g

export function touchesRecords(tool: string, input: string): boolean {
  if (!WRITE_TOOLS.includes(tool)) return false
  return [...input.matchAll(TEST_FOLDER_FILE)].some(m => m[1] !== 'report.md')
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

// The relay record rule of SPEC.md section 2, the same as `record.read_rows` in Python. Each field
// has its allowed JSON types. A text field also needs its hash.
const RELAY_FIELDS: Record<string, Record<string, string[]>> = {
  turn: { ts: ['number'], harness: ['string'], said: ['string'], shown: ['string', 'null'] },
  blocked_call: { ts: ['number'], harness: ['string'], tool: ['string'], detail: ['string'] },
}
const RELAY_OPTIONAL: Record<string, Record<string, string>> = { turn: { ok: 'boolean', session: 'string' } }
const TEXT_FIELDS = ['said', 'shown']
const SINCE_02 = ['model_session', 'started', 'originator', 'stream']

function jsonType(value: unknown): string {
  return value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value
}

function hasLoneSurrogate(value: unknown): boolean {
  if (typeof value === 'string') return LONE_SURROGATE.test(value)
  if (value !== null && typeof value === 'object') {
    return Object.entries(value).some(([k, v]) => LONE_SURROGATE.test(k) || hasLoneSurrogate(v))
  }
  return false
}

// Why one line of a relay record is not valid, or null if it is valid.
async function relayLineError(raw: string): Promise<string | null> {
  let row: any
  try {
    row = JSON.parse(raw)
  } catch {
    return 'not JSON'
  }
  if (jsonType(row) !== 'object') return 'not a JSON object'
  if (hasLoneSurrogate(row)) return 'a field has a lone surrogate, which is not a Unicode scalar value'
  if (row.v !== '0.1' && row.v !== '0.2') return `version ${JSON.stringify(row.v)}, expected one of 0.1, 0.2`
  const fields = Object.hasOwn(RELAY_FIELDS, row.type) ? RELAY_FIELDS[row.type] : null
  if (fields === null) return `unknown type ${JSON.stringify(row.type)} in a relay record`
  for (const [name, types] of Object.entries(fields)) {
    if (!(name in row)) return `missing field '${name}'`
    if (!types.includes(jsonType(row[name]))) return `field '${name}' has the wrong type`
    if (TEXT_FIELDS.includes(name)) {
      const hash = `${name}_sha256`
      if (!(hash in row) || row[hash] !== (await sha256(row[name]))) return `field ${hash} does not match '${name}'`
    }
  }
  for (const [name, type] of Object.entries(RELAY_OPTIONAL[row.type] ?? {})) {
    if (name in row && jsonType(row[name]) !== type) return `field '${name}' has the wrong type`
  }
  if (row.v === '0.1' && [row.type, ...Object.keys(row)].some(k => SINCE_02.includes(k))) {
    return 'a field or a type of version 0.2 in a version 0.1 row'
  }
  if ('error' in row && typeof row.error !== 'string') return "field 'error' has the wrong type"
  return null
}

// The turns of a relay record, of one session or (with null) of all sessions. An invalid line or a
// wrong hash throws an Error that names the file and the line. Never skip such a line.
export async function relayTurns(text: string, path: string, session: string | null): Promise<VerbatimRelayTurn[]> {
  const lines = text.split('\n')
  if (lines.length && lines[lines.length - 1] === '') lines.pop()
  const turns: VerbatimRelayTurn[] = []
  for (const [i, raw] of lines.entries()) {
    const error = await relayLineError(raw)
    if (error !== null) throw new Error(`${path}: line ${i + 1}: ${error}`)
    const row = JSON.parse(raw)
    if (row.type === 'turn' && (session === null || row.session === session)) {
      turns.push({ said: row.said, shown: row.shown, ok: row.ok === true })
    }
  }
  return turns
}

// The shell command check of the deny rules (SPEC.md section 5), the same as
// src/verbatim_relay/commands.py. A command passes if each of its commands is a read program and
// each output redirect writes /dev/null or report.md. Input that does not parse fails.
const SHELL_TOOLS = ['Bash', 'shell', 'local_shell', 'exec_command']
const SHELLS = ['bash', 'sh', 'zsh']
const OPS = '();<>|&'
const HEREDOC = /(?<!<)<<(?!<)(-?)\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\2/g
// A sed script reads only if, without its /regex/ addresses, it has only these characters: line
// addresses and the commands p, P, =, q, Q, d and n. So s, w, W, e and r fail.
const SED_ADDRESS = /\/(?:\\.|[^/\\])*\/I?/g
const SED_READS = /^[0-9$,;!\s/pP=qQdn{}+~]*$/
const SED_FLAGS = 'nErsuz'
const SED_VALUES = 'el'
const SED_LONG = ['--regexp-extended', '--null-data', '--separate', '--unbuffered', '--posix']
const FIND_ACTIONS = ['-delete', '-exec', '-execdir', '-ok', '-okdir', '-fls', '-fprint', '-fprint0', '-fprintf']
// trace writes trace.jsonl and findings.json, and check starts a test, so they are not here.
const VIEWS = ['transcript', 'audit', 'status', 'view']
// The file types of an entry argument that names a program file.
const CODE = ['.py', '.js', '.mjs', '.cjs', '.ts', '.sh', '.rb']

function short(args: string[], letter: string): boolean {
  return args.some(a => a.startsWith('-') && !a.startsWith('--') && a.slice(1).includes(letter))
}

// True for sed -n with scripts that only print. An unknown option fails.
function sedReads(args: string[]): boolean {
  let quiet = false
  const scripts: string[] = []
  const rest: string[] = []
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === '--quiet' || a === '--silent') {
      quiet = true
    } else if (a.startsWith('--expression=')) {
      scripts.push(a.slice(a.indexOf('=') + 1))
    } else if (a === '--expression') {
      if (i + 1 >= args.length) return false
      scripts.push(args[++i])
    } else if (a.startsWith('--')) {
      if (!SED_LONG.includes(a)) return false
    } else if (a.startsWith('-') && a.length > 1) {
      for (let k = 1; k < a.length; k++) {
        const ch = a[k]
        if (ch === 'n') {
          quiet = true
        } else if (SED_VALUES.includes(ch)) {
          let value = a.slice(k + 1)
          if (!value) {
            if (i + 1 >= args.length) return false
            value = args[++i]
          }
          if (ch === 'e') scripts.push(value)
          break
        } else if (!SED_FLAGS.includes(ch)) {
          return false
        }
      }
    } else {
      rest.push(a)
    }
  }
  if (!scripts.length) {
    if (!rest.length) return false
    scripts.push(rest[0])
  }
  return quiet && scripts.every(x => SED_READS.test(x.replace(SED_ADDRESS, '')))
}

const ANY = (): boolean => true
const READS: Record<string, (args: string[]) => boolean> = {
  ...Object.fromEntries(['cat', 'head', 'tail', 'grep', 'egrep', 'fgrep', 'jq', 'wc', 'ls', 'nl', 'cut'].map(p => [p, ANY])),
  ...Object.fromEntries(['diff', 'cmp', 'stat', 'sha256sum', 'shasum', 'echo', 'printf', 'pwd', 'cd'].map(p => [p, ANY])),
  rg: args => !args.some(a => a.startsWith('--pre')),
  sed: sedReads,
  sort: args => !short(args, 'o') && !args.some(a => a.startsWith('--output')),
  find: args => !args.some(a => FIND_ACTIONS.includes(a)),
  'verbatim-relay': args => args.length > 0 && VIEWS.includes(args[0]),
}

function stripHeredocs(text: string): string {
  const out: string[] = []
  const ends: [string, boolean][] = []
  for (const line of text.split('\n')) {
    if (ends.length) {
      const [end, dash] = ends[0]
      if ((dash ? line.replace(/^\t+/, '') : line) === end) ends.shift()
      continue
    }
    out.push(line)
    for (const m of line.matchAll(HEREDOC)) ends.push([m[3], m[1] === '-'])
  }
  return out.join('\n')
}

// The words and operators of a command, as [text, isOperator], or null if it does not parse.
export function tokens(text: string): [string, boolean][] | null {
  const out: [string, boolean][] = []
  let word: string | null = null
  const flush = (): void => {
    if (word !== null) out.push([word, false])
    word = null
  }
  const n = text.length
  for (let i = 0; i < n; i++) {
    const c = text[i]
    if (c === '\n') {
      flush()
      out.push([';', true])
    } else if (c === ' ' || c === '\t') {
      flush()
    } else if (c === "'") {
      const j = text.indexOf("'", i + 1)
      if (j < 0) return null
      word = (word ?? '') + text.slice(i + 1, j)
      i = j
    } else if (c === '"') {
      let j = i + 1
      let part = ''
      while (j < n && text[j] !== '"') {
        if (text[j] === '`' || text.startsWith('$(', j)) return null
        if (text[j] === '\\' && j + 1 < n) j++
        part += text[j]
        j++
      }
      if (j >= n) return null
      word = (word ?? '') + part
      i = j
    } else if (c === '\\') {
      if (i + 1 >= n) return null
      if (text[i + 1] !== '\n') word = (word ?? '') + text[i + 1]
      i++
    } else if (c === '`') {
      return null
    } else if (OPS.includes(c)) {
      flush()
      let j = i
      while (j < n && OPS.includes(text[j])) j++
      out.push([text.slice(i, j), true])
      i = j - 1
    } else {
      word = (word ?? '') + c
    }
  }
  flush()
  return out
}

// A part with only variable assignments passes, for example T=.verbatim-relay/tests/x. These
// variables change how the shell finds or runs a program, so an assignment to them fails.
const SHELL_VARIABLES = ['PATH', 'IFS', 'CDPATH', 'ENV', 'BASH_ENV', 'SHELLOPTS', 'BASHOPTS', 'PS4', 'PROMPT_COMMAND']

function assignment(word: string): boolean {
  const m = /^([A-Za-z_][A-Za-z0-9_]*)=/.exec(word)
  return m !== null && !SHELL_VARIABLES.includes(m[1]) && !m[1].startsWith('LD_') && !m[1].startsWith('DYLD_')
}

function writesOnlyReport(target: string): boolean {
  return target === '/dev/null' || target.split('/').pop() === 'report.md'
}

export function readsOnly(command: string): boolean {
  const toks = tokens(stripHeredocs(command))
  if (toks === null) return false
  const segments: string[][] = [[]]
  for (let i = 0; i < toks.length; i++) {
    const [text, op] = toks[i]
    if (!op) {
      segments[segments.length - 1].push(text)
    } else if (text.includes('(') || text.includes(')')) {
      return false
    } else if ([...text].every(ch => ';&|'.includes(ch))) {
      segments.push([])
    } else {
      const next = toks[i + 1]
      if (next === undefined || next[1]) return false
      const dup = text.endsWith('&') && (/^\d+$/.test(next[0]) || next[0] === '-')
      if (text.includes('>') && !dup && !writesOnlyReport(next[0])) return false
      i++
    }
  }
  return segments.every(words => {
    if (words.every(assignment)) return true
    const check = READS[words[0].split('/').pop()!]
    return check !== undefined && check(words.slice(1))
  })
}

// The command of a shell tool call, or null if the tool is not a shell.
export function commandOf(tool: string, input: any): string | null {
  if (!SHELL_TOOLS.includes(tool) || input === null || typeof input !== 'object') return null
  const cmd = input.command ?? input.cmd ?? input.input?.command
  if (typeof cmd === 'string') return cmd
  if (Array.isArray(cmd) && cmd.every(x => typeof x === 'string')) {
    if (cmd.length >= 3 && SHELLS.includes(cmd[0].split('/').pop()) && ['-c', '-lc'].includes(cmd[1])) return cmd[2]
    return cmd.map(x => (/^[\w@%+=:,./-]+$/.test(x) ? x : `'${x.replace(/'/g, `'"'"'`)}'`)).join(' ')
  }
  return null
}

export function toolReadsOnly(tool: string, input: any): boolean {
  const cmd = commandOf(tool, input)
  return cmd !== null && readsOnly(cmd)
}

// The names that mark a run of the entry: its program files, and the module after -m.
export function entryNames(entry: readonly string[]): string[] {
  const names: string[] = []
  entry.forEach((arg, k) => {
    const base = arg.split('/').pop()!
    const dot = base.lastIndexOf('.')
    if (dot >= 0 && CODE.includes(base.slice(dot))) names.push(base)
    else if (k > 0 && entry[k - 1] === '-m') names.push(arg)
  })
  return names
}

function globMatch(glob: string, name: string): boolean {
  let re = ''
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i]
    const end = c === '[' ? glob.indexOf(']', i + 2) : -1
    if (c === '*') re += '.*'
    else if (c === '?') re += '.'
    else if (end > 0) {
      const body = glob.slice(i + 1, end)
      re += `[${body.startsWith('!') ? '^' + body.slice(1) : body}]`
      i = end
    } else re += escape(c)
  }
  return new RegExp(`^${re}$`, 's').test(name)
}

// True if the text, or a word of the shell command, names a program file or the module of the
// entry. A word is compared after the shell removes its quotes and escapes, and a word with a
// glob character is compared as a glob.
export function namesEntry(text: string, names: readonly string[], command: string | null = null): boolean {
  if (names.some(x => new RegExp(`(?<![\\w.-])${escape(x)}(?![\\w-])`).test(text))) return true
  const toks = command === null ? [] : (tokens(stripHeredocs(command)) ?? [])
  for (const [word, op] of toks) {
    if (op) continue
    const base = word.split('/').pop()!
    for (const x of names) {
      if (x === word || x === base) return true
      if (/[*?[]/.test(word) && (globMatch(base, x) || globMatch(word, x))) return true
    }
  }
  return false
}
