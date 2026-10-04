import { expect, test } from 'claude-code/testing'

import { denyPattern, isNetworkTool, pick, requestBody, sha256 } from './core'

const TRICKY = 'Hi, I want to return order #4471.  \n\nÜnïcödé € ₹\t| a | b |\n'
const REPLY = '## Toy shop  \nYou wrote it.\n\n| item | price |\n|---|---|\n| mug | € 8 |\n'
const OPTIONS = { start_on: true, record: '/virtual/relay.jsonl' }

// Fakes for the tap and the file system, under the plugin. A file system hook answers
// { value }, or { deny } for a call that rejects.
function fakes(on: any, reply: (body: string) => { status: number; text: string }) {
  const files: Record<string, string> = {}
  const sent: { url: string; body: string }[] = []
  const logs: string[] = []
  on('http.fetch', async (_$: any, e: any) => {
    sent.push({ url: e.url, body: e.init.body })
    const r = reply(e.init.body)
    return { value: { status: r.status, ok: r.status >= 200 && r.status < 300, headers: {}, text: r.text } }
  })
  on('fs.stat', async (_$: any, e: any) =>
    e.path in files
      ? { value: { kind: 'file', size: files[e.path].length, mtimeMs: 0, isLink: false } }
      : { deny: `ENOENT: no such file: ${e.path}` },
  )
  on('fs.read', async (_$: any, e: any) => ({ value: files[e.path] }))
  on('fs.write', async (_$: any, e: any) => {
    files[e.path] = e.text
    return { value: undefined }
  })
  on('ui.log', async (_$: any, e: any) => {
    logs.push(e.text)
    return { value: undefined }
  })
  on('ui.status', async () => ({ value: undefined }))
  return { files, sent, logs }
}

function rows(text: string | undefined) {
  return (text ?? '').split('\n').filter(Boolean).map(line => JSON.parse(line))
}

test('relay mode sends the exact bytes, shows the exact reply, and keeps the model out', { options: OPTIONS }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: JSON.stringify({ reply: REPLY }) }))
  const result: any = await $.prompt.submit({ text: TRICKY })
  expect('drop' in result).toBe(true)
  expect(JSON.parse(f.sent[0].body)).toEqual({ text: TRICKY })
  expect(f.sent[0].url).toBe('http://127.0.0.1:8800/')
  expect(f.logs).toEqual([REPLY])
  const [row] = rows(f.files['/virtual/relay.jsonl'])
  expect(row).toMatchObject({ v: '0.1', type: 'turn', harness: 'claude-code', said: TRICKY, shown: REPLY })
  expect(row.said_sha256).toBe(await sha256(TRICKY))
  expect(row.shown_sha256).toBe(await sha256(REPLY))
})

test('relay mode off passes the prompt on', { options: { ...OPTIONS, start_on: false } }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: '{}' }))
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit({ text: 'hello' })
  expect(result.text).toBe('hello')
  expect(f.sent.length).toBe(0)
})

test('an agent error is shown and recorded as shown', { options: OPTIONS }, async ($, on) => {
  const f = fakes(on, () => ({ status: 500, text: '{"error": "boom"}' }))
  await $.prompt.submit({ text: 'hi' })
  expect(f.logs[0]).toBe('verbatim-relay: the agent returned HTTP 500:\n{"error": "boom"}')
  expect(rows(f.files['/virtual/relay.jsonl'])[0].shown).toBe(f.logs[0])
})

test('the openai adapter sends the conversation so far', { options: { ...OPTIONS, adapter: 'openai', openai_model: 'toy' } }, async ($, on) => {
  let n = 0
  const f = fakes(on, () => ({ status: 200, text: JSON.stringify({ choices: [{ message: { content: `r${++n}` } }] }) }))
  await $.prompt.submit({ text: 'first' })
  await $.prompt.submit({ text: 'second' })
  expect(JSON.parse(f.sent[1].body)).toEqual({
    model: 'toy',
    stream: false,
    messages: [
      { role: 'user', content: 'first' },
      { role: 'assistant', content: 'r1' },
      { role: 'user', content: 'second' },
    ],
  })
})

test('a model call to the tap is denied and recorded; a file write is not', { options: OPTIONS }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: '{}' }))
  on('tool.call', async () => ({ result: 'ran' }))
  const denied: any = await $.tool.call({ tool: 'Bash', command: 'curl -s http://localhost:8800/ -d x' } as any)
  expect(typeof denied.deny).toBe('string')
  expect(rows(f.files['/virtual/relay.jsonl'])[0]).toMatchObject({ type: 'blocked_call', tool: 'Bash' })
  const allowed: any = await $.tool.call({ tool: 'Write', file_path: '/tmp/x', content: 'http://127.0.0.1:8800/' } as any)
  expect(allowed.deny).toBe(undefined)
})

test('pure parts', async () => {
  expect(pick({ a: [{ b: 'x' }] }, 'a.0.b')).toBe('x')
  expect(JSON.parse(requestBody({ adapter: 'json', message_field: 'input.text' } as any, 'hi', []))).toEqual({
    input: { text: 'hi' },
  })
  const p = denyPattern(['http://127.0.0.1:8800/', 'https://agent.example.com/chat'])!
  expect(p.test('curl http://[::1]:8800/')).toBe(true)
  expect(p.test('curl http://127.0.0.1:88001/')).toBe(false)
  expect(p.test('wget https://agent.example.com/x')).toBe(true)
  expect(p.test('agent.example.community')).toBe(false)
  expect(isNetworkTool('mcp__fetch__get')).toBe(true)
  expect(isNetworkTool('mcp__verbatim-relay__transcript')).toBe(false)
  expect(isNetworkTool('Edit')).toBe(false)
  expect(await sha256('é')).toBe('4a99557e4033c3539de2eb65472017cad5f9557f7a0625a09f1c3f6e2ba69c4c')
})
