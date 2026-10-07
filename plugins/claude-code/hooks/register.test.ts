import { expect, test } from 'claude-code/testing'

import { contractBody, contractShown, denyPattern, entryNames, isChecked, isStream, namesEntry, pick, readsOnly, replyText, requestBody, sha256, sseEvents, streamText, toolReadsOnly, touchesRecords, touchesTestFiles } from './core'

const TRICKY = 'Hi, I want to return order #4471.  \n\nÜnïcödé € ₹\t| a | b |\n'
const REPLY = '## Toy shop  \nYou wrote it.\n\n| item | price |\n|---|---|\n| mug | € 8 |\n'
const OPTIONS = { start_on: true, record: '/virtual/relay.jsonl' }

// Fakes for the tap and the file system, under the plugin. A file system hook answers
// { value }, or { deny } for a call that rejects.
function fakes(on: any, reply: (body: string) => { status: number; text: string; headers?: Record<string, string> }) {
  const files: Record<string, string> = {}
  const sent: { url: string; body: string }[] = []
  const logs: string[] = []
  on('http.fetch', async (_$: any, e: any) => {
    sent.push({ url: e.url, body: e.init.body })
    const r = reply(e.init.body)
    return { value: { status: r.status, ok: r.status >= 200 && r.status < 300, headers: r.headers ?? {}, text: r.text } }
  })
  // $.fs resolves a relative path against the working directory. Key the files by the path
  // from .verbatim-relay/ on, as the plugin wrote it.
  const key = (path: string) => path.replace(/^.*?(?=\.verbatim-relay\/)/, '')
  on('fs.stat', async (_$: any, e: any) =>
    key(e.path) in files
      ? { value: { kind: 'file', size: files[key(e.path)].length, mtimeMs: 0, isLink: false } }
      : { deny: `ENOENT: no such file: ${e.path}` },
  )
  on('fs.read', async (_$: any, e: any) => ({ value: files[key(e.path)] }))
  on('fs.write', async (_$: any, e: any) => {
    files[key(e.path)] = e.text
    return { value: undefined }
  })
  on('ui.log', async (_$: any, e: any) => {
    logs.push(e.text)
    return { value: undefined }
  })
  on('ui.status', async () => ({ value: undefined }))
  on('ui.open', async () => ({ value: undefined }))
  on('session.id', async () => ({ value: 's1' }))
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
  expect(row).toMatchObject({ v: '0.2', type: 'turn', harness: 'claude-code', said: TRICKY, shown: REPLY, ok: true, session: 's1' })
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

// An OpenAI-style SSE body with 5 characters of the reply in each chunk.
function sse(reply: string, done = true): string {
  let body = ': the toy shop streams\n\n'
  for (let i = 0; i < reply.length; i += 5) body += `data: ${JSON.stringify({ choices: [{ index: 0, delta: { content: reply.slice(i, i + 5) } }] })}\n\n`
  return body + (done ? 'data: [DONE]\n\n' : '')
}
const SSE = { 'content-type': 'text/event-stream; charset=utf-8' }

test('the openai adapter shows a streamed reply when the stream is complete', { options: { ...OPTIONS, adapter: 'openai' } }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: sse(REPLY), headers: SSE }))
  await $.prompt.submit({ text: TRICKY })
  expect(f.logs).toEqual([REPLY])
  expect(rows(f.files['/virtual/relay.jsonl'])[0]).toMatchObject({ shown: REPLY, ok: true })
})

test('a stream that ends early is an error, not a part of the reply', { options: { ...OPTIONS, adapter: 'openai' } }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: sse(REPLY, false), headers: SSE }))
  await $.prompt.submit({ text: TRICKY })
  expect(f.logs).toEqual(['verbatim-relay: cannot read the reply: the stream ended before data: [DONE]'])
  expect(rows(f.files['/virtual/relay.jsonl'])[0]).toMatchObject({ shown: f.logs[0], ok: false })
})

test('stream parts', async () => {
  expect(sseEvents('﻿: c\r\nevent: note\r\ndata: a\r\ndata:b\r\n\r\ndata: c\rdata: d\n\n\nevent: x\n\ndata: last')).toEqual([
    { name: 'note', data: 'a\nb' },
    { name: 'message', data: 'c\nd' },
    { name: 'message', data: 'last' },
  ])
  const chunk = (content: unknown, index = 0) => `data: ${JSON.stringify({ choices: [{ index, delta: { content } }] })}\n\n`
  const done = 'data: [DONE]\n\n'
  expect(streamText(chunk('## Toy') + chunk('other', 1) + 'data: {"choices": []}\n\n' + chunk(' shop') + done)).toBe('## Toy shop')
  const failures: [string, string][] = [
    [chunk('a'), 'ended before data: [DONE]'],
    [chunk('a') + done + chunk('b'), 'after data: [DONE]'],
    [chunk('a') + 'data: {"error": {"message": "down"}}\n\n' + done, 'an error:'],
    [chunk('a') + 'event: error\ndata: down\n\n' + done, 'error event'],
    ['data: {"choices": [{"delta": {"con\n\n' + done, 'not JSON'],
    ['data: [1, 2]\n\n' + done, 'not a JSON object'],
    ['data: {"choices": {}}\n\n' + done, 'not a list'],
    ['data: {"choices": [{"delta": "a"}]}\n\n' + done, "no 'delta' object"],
    [chunk(4471) + done, 'not a string'],
    ['data: {"choices": [{"delta": {"tool_calls": []}}]}\n\n' + done, "no chunk of the stream has a 'delta.content' text"],
  ]
  for (const [body, error] of failures) expect(() => streamText(body)).toThrow(error)
  expect(isStream('Text/Event-Stream; charset=utf-8')).toBe(true)
  expect(isStream('application/json')).toBe(false)
  expect(() => replyText({ adapter: 'json', reply_field: 'reply' } as any, sse('hi'), 'text/event-stream')).toThrow('does not read a streamed response')
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
  expect(isChecked('mcp__fetch__get')).toBe(true)
  expect(isChecked('SomeNewTool')).toBe(true)
  expect(isChecked('mcp__verbatim-relay__transcript')).toBe(false)
  expect(isChecked('Edit')).toBe(false)
  expect(await sha256('é')).toBe('4a99557e4033c3539de2eb65472017cad5f9557f7a0625a09f1c3f6e2ba69c4c')
})

test('the transcript tool reads this session from the record', { options: OPTIONS }, async ($, on) => {
  const f = fakes(on, () => ({ status: 200, text: JSON.stringify({ reply: REPLY }) }))
  f.files['/virtual/relay.jsonl'] = JSON.stringify({ type: 'turn', said: 'other', shown: 'x', ok: true, session: 's0' }) + '\n'
  await $.prompt.submit({ text: TRICKY })
  const out: any = await $.tool.call({ tool: 'mcp__verbatim-relay__transcript' } as any)
  expect(JSON.parse(out.result)).toEqual([{ said: TRICKY, shown: REPLY, ok: true }])
})

// A test (SPEC.md section 7). The fake verbatim-relay command writes current.json, as the bridge does.
const DIR = '.verbatim-relay/tests/20261005-120000-ab12'
const CURRENT = { v: 1, test: '20261005-120000-ab12', dir: DIR, tap_url: 'http://127.0.0.1:8811/', pid: 4471 }

function withTest(on: any, f: ReturnType<typeof fakes>, evaluation: string | null = 'Evaluate the test.') {
  const runs: string[][] = []
  f.files['.verbatim-relay/config.json'] = JSON.stringify({ entry: ['python', 'examples/toy-shop/agent.py'], models: [] })
  on('process.run', async (_$: any, e: any) => {
    runs.push(e.argv)
    if (e.argv[1] === 'start') {
      f.files['.verbatim-relay/current.json'] = JSON.stringify(CURRENT)
      f.files['.verbatim-relay/mode'] = 'on\n'
      return { value: { exitCode: 0, stdout: JSON.stringify(CURRENT) + '\n', stderr: '' } }
    }
    delete f.files['.verbatim-relay/current.json']
    f.files['.verbatim-relay/mode'] = 'off\n'
    if (e.argv.includes('--evaluation')) {
      const out = { text: 'Test 20261005-120000-ab12 ended: 1 turns, 0 model sessions.', evaluation }
      return { value: { exitCode: 0, stdout: JSON.stringify(out) + '\n', stderr: '' } }
    }
    return { value: { exitCode: 0, stdout: 'Test 20261005-120000-ab12 ended: 1 turns, 0 model sessions.\n', stderr: '' } }
  })
  return runs
}

function contractReply(body: string) {
  const { id } = JSON.parse(body)
  return { status: 200, text: JSON.stringify({ v: 1, id, reply: REPLY }) }
}

test('a test starts, relays with the contract, records in its folder and ends', { options: { record: '/virtual/relay.jsonl' } }, async ($, on) => {
  const f = fakes(on, contractReply)
  const runs = withTest(on, f)
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const started: any = await $.command.run({ command: 'verbatim-relay', args: 'start' } as any)
  expect(started.text).toContain('Test 20261005-120000-ab12 started')
  expect(runs[0]).toEqual(['verbatim-relay', 'start', '--json', '--tester-session', 's1'])
  await $.prompt.submit({ text: TRICKY })
  await $.prompt.submit({ text: 'second' })
  expect(f.sent[0].url).toBe(CURRENT.tap_url)
  const first = JSON.parse(f.sent[0].body)
  expect(first).toMatchObject({ v: 1, session: CURRENT.test, message: TRICKY, history: [] })
  expect(JSON.parse(f.sent[1].body).history).toEqual([{ message: TRICKY, reply: REPLY }])
  expect(f.logs).toEqual([REPLY, REPLY])
  const turns = rows(f.files[`${DIR}/relay.jsonl`])
  expect(turns[0]).toMatchObject({ v: '0.2', type: 'turn', said: TRICKY, shown: REPLY, ok: true, session: 's1' })
  expect(f.files['/virtual/relay.jsonl']).toBe(undefined)
  const transcript: any = await $.tool.call({ tool: 'mcp__verbatim-relay__transcript' } as any)
  expect(JSON.parse(transcript.result).length).toBe(2)
  const ended: any = await $.command.run({ command: 'verbatim-relay', args: 'end' } as any)
  expect(runs[1]).toEqual(['verbatim-relay', 'end'])
  expect(ended.text).toContain('Relay mode is off.')
  const after: any = await $.prompt.submit({ text: 'to the model' })
  expect(after.drop).toBe(undefined)
})

test('relay mode with an entry and no test fails closed', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  f.files['.verbatim-relay/config.json'] = JSON.stringify({ entry: ['python', 'agent.py'] })
  f.files['.verbatim-relay/mode'] = 'on\n'
  const result: any = await $.prompt.submit({ text: 'hi' })
  expect('drop' in result).toBe(true)
  expect(f.sent.length).toBe(0)
  expect(f.logs[0]).toContain('no test runs')
})

test('a test that does not start leaves relay mode off', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  f.files['.verbatim-relay/config.json'] = JSON.stringify({ entry: ['python', 'agent.py'] })
  on('process.run', async () => ({ value: { exitCode: 1, stdout: '{"error": "the entry exited at start"}\n', stderr: '' } }))
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const started: any = await $.command.run({ command: 'verbatim-relay', args: 'on' } as any)
  expect(started.text).toBe('The test did not start: the entry exited at start')
  const result: any = await $.prompt.submit({ text: 'hello' })
  expect(result.text).toBe('hello')
})

test('a running test keeps relay mode after the plugin reloads', { options: { start_on: false } }, async ($, on) => {
  // A new plugin state, with start_on false. The mode file and current.json say that a test runs.
  const f = fakes(on, contractReply)
  withTest(on, f)
  f.files['.verbatim-relay/current.json'] = JSON.stringify(CURRENT)
  f.files['.verbatim-relay/mode'] = 'on\n'
  const result: any = await $.prompt.submit({ text: TRICKY })
  expect('drop' in result).toBe(true)
  expect(f.sent[0].url).toBe(CURRENT.tap_url)
})

test('with an entry, start_on alone does not switch relay mode on', { options: { start_on: true } }, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit({ text: 'hello' })
  expect(result.text).toBe('hello')
  expect(f.sent.length).toBe(0)
})

test('during a test, the model cannot change the test files or call the tap', { options: { start_on: true } }, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  f.files['.verbatim-relay/current.json'] = JSON.stringify(CURRENT)
  on('tool.call', async () => ({ result: 'ran' }))
  const write: any = await $.tool.call({ tool: 'Edit', file_path: '.verbatim-relay/entry.py', old_string: 'a', new_string: 'b' } as any)
  expect(typeof write.deny).toBe('string')
  const curl: any = await $.tool.call({ tool: 'Bash', command: 'curl -s http://127.0.0.1:8811/' } as any)
  expect(typeof curl.deny).toBe('string')
  const read: any = await $.tool.call({ tool: 'Read', file_path: '.verbatim-relay/config.json' } as any)
  expect(read.deny).toBe(undefined)
  expect(rows(f.files[`${DIR}/relay.jsonl`]).map(r => r.tool)).toEqual(['Edit', 'Bash'])
})

test('contract parts', async () => {
  const turns = [
    { said: 'a', shown: 'b', ok: true },
    { said: 'c', shown: 'verbatim-relay: HTTP 502: x', ok: false },
  ]
  expect(JSON.parse(contractBody('m-1', 't-1', 'd', turns))).toEqual({
    v: 1,
    id: 'm-1',
    session: 't-1',
    message: 'd',
    history: [{ message: 'a', reply: 'b' }],
  })
  expect(contractBody('m-1', 't-1', 'x\u2028y', [])).not.toContain('\n')
  expect(contractShown(200, '{"v": 1, "id": "m-1", "reply": "Hi  "}', 'm-1')).toEqual({ shown: 'Hi  ', ok: true })
  expect(contractShown(200, '{"v": 1, "id": "m-0", "reply": "Hi"}', 'm-1').ok).toBe(false)
  expect(contractShown(500, '{"v": 1, "id": "m-1", "error": "down"}', 'm-1')).toEqual({
    shown: 'verbatim-relay: the agent sent an error:\ndown',
    ok: false,
  })
  expect(contractShown(502, '{"error": "the agent exited (code 3)"}', 'm-1').shown).toBe('verbatim-relay: HTTP 502: the agent exited (code 3)')
  expect(touchesTestFiles('Write', '{"file_path": ".verbatim-relay/entry.py"}')).toBe(true)
  expect(touchesTestFiles('Read', '{"file_path": ".verbatim-relay/entry.py"}')).toBe(false)
  expect(touchesTestFiles('Bash', '{"command": "verbatim-relay transcript"}')).toBe(false)
})

test('the prompt verbatim-relay end ends the test and gives the model the evaluation', { options: { start_on: false } }, async ($, on) => {
  const f = fakes(on, contractReply)
  const runs = withTest(on, f)
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text, context: e.context }))
  await $.command.run({ command: 'verbatim-relay', args: 'start' } as any)
  const result: any = await $.prompt.submit({ text: 'verbatim-relay end' })
  expect(runs[1]).toEqual(['verbatim-relay', 'end', '--evaluation'])
  expect(result.text).toBe('verbatim-relay end')
  expect(result.context.at(-1)).toContain('Evaluate the test.')
  expect(result.context.at(-1)).toContain('ended: 1 turns')
  expect(f.sent.length).toBe(0)
})

test('with no evaluation, the prompt verbatim-relay end does not reach the model', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f, null)
  on('prompt.submit', async (_$: any, e: any) => ({ text: e.text }))
  const result: any = await $.prompt.submit({ text: 'verbatim-relay end' })
  expect('drop' in result).toBe(true)
  expect(f.logs[0]).toContain('Relay mode is off.')
})

test('the prompts verbatim-relay start and status run and are never relayed', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  const runs = withTest(on, f)
  const started: any = await $.prompt.submit({ text: 'verbatim-relay start' })
  expect('drop' in started).toBe(true)
  expect(runs[0][1]).toBe('start')
  const status: any = await $.prompt.submit({ text: 'verbatim-relay status' })
  expect('drop' in status).toBe(true)
  expect(f.logs.at(-1)).toContain(`Test ${CURRENT.test} runs`)
  expect(f.sent.length).toBe(0)
})

test('after a test, the model can write report.md and no other test file', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  on('tool.call', async () => ({ result: 'ran' }))
  const folder = '.verbatim-relay/tests/20261005-120000-ab12'
  const report: any = await $.tool.call({ tool: 'Write', file_path: `${folder}/report.md`, content: '# Report' } as any)
  expect(report.deny).toBe(undefined)
  const tap: any = await $.tool.call({ tool: 'Edit', file_path: `${folder}/tap.jsonl`, old_string: 'a', new_string: 'b' } as any)
  expect(typeof tap.deny).toBe('string')
  const config: any = await $.tool.call({ tool: 'Write', file_path: '.verbatim-relay/config.json', content: '{}' } as any)
  expect(config.deny).toBe(undefined)
  expect(touchesRecords('Write', `"${folder}/sessions/codex/r.jsonl"`)).toBe(true)
  expect(touchesRecords('Read', `"${folder}/tap.jsonl"`)).toBe(false)
})

// The same table as tests/test_commands.py.
const F = '.verbatim-relay/tests/20261006-080000-cc01'
const READS = [
  "cat {F}/findings.json",
  "sed -n '1,200p' {F}/trace.jsonl",
  "sed -n '/refund/p' {F}/trace.jsonl",
  "sed -n -e '1,5p' -e '/a\\/w/p' {F}/trace.jsonl",
  "verbatim-relay audit --json",
  "T={F}; ls $T; cat $T/findings.json",
  "jq '.findings[] | .check' {F}/findings.json",
  "ls -la {F} && wc -l {F}/tap.jsonl",
  "grep -n refund {F}/trace.jsonl | head -5",
  "cat {F}/audit.json 2>/dev/null",
  "cat {F}/audit.json 2>&1 | tail -n 3",
  "cat > {F}/report.md <<'EOF'\n# Test: evaluation\nIt's done; rm -rf $(x) > a\nEOF",
  "cd {F}\nsort -n tap.jsonl",
  "verbatim-relay transcript --trace --test 20261006-080000-cc01",
  "find {F} -name '*.jsonl'",
  "cat \"{F}/manifest.json\"",
].map(c => c.replaceAll('{F}', F))
const WRITES = [
  "sed -i '' 's/a/b/' {F}/trace.jsonl",
  "sed -ni 's/a/b/p' {F}/trace.jsonl",
  "sed -n '1w {F}/x' {F}/trace.jsonl",
  "sed -n 's/a/b/w{F}/tap.jsonl' {F}/trace.jsonl",
  "sed -n -e p -f script.sed {F}/trace.jsonl",
  "sed -n --in-place p {F}/trace.jsonl",
  "cat {F}/a > {F}/trace.jsonl",
  "echo x >> {F}/findings.json",
  "rm {F}/trace.jsonl",
  "cd {F} && rm trace.jsonl",
  "cat {F}/tap.jsonl | tee {F}/copy",
  "cat {F}/tap.jsonl | python3 -m json.tool",
  "sort -o {F}/tap.jsonl {F}/tap.jsonl",
  "find {F} -delete",
  "cat $(rm {F}/tap.jsonl)",
  "cat \"$(rm {F}/tap.jsonl)\"",
  "cat `rm {F}/tap.jsonl`",
  "(cat {F}/tap.jsonl)",
  "X=1 cat {F}/tap.jsonl",
  "PATH=.; cat {F}/tap.jsonl",
  "LD_PRELOAD=x.so; cat {F}/tap.jsonl",
  "T=$(rm {F}/tap.jsonl)",
  "cat '{F}/tap.jsonl",
  "verbatim-relay end",
  "verbatim-relay trace --root {F}/../../..",
  "verbatim-relay check",
  "python entry.py",
].map(c => c.replaceAll('{F}', F))

test('the shell command check', async () => {
  for (const c of READS) expect([c, readsOnly(c)]).toEqual([c, true])
  for (const c of WRITES) expect([c, readsOnly(c)]).toEqual([c, false])
  expect(toolReadsOnly('shell', { command: ['bash', '-lc', 'cat a | head'] })).toBe(true)
  expect(toolReadsOnly('shell', { command: ['cat', 'a b'] })).toBe(true)
  expect(toolReadsOnly('shell', { command: ['rm', 'a'] })).toBe(false)
  expect(toolReadsOnly('mcp__files__read', { path: 'a' })).toBe(false)
  expect(entryNames(['uv', 'run', '--project', '/srv/shop', 'python', '/srv/shop/entry.py'])).toEqual(['entry.py'])
  expect(entryNames(['python', '-m', 'shop.entry'])).toEqual(['shop.entry'])
  expect(entryNames(['npm', 'run', 'agent'])).toEqual([])
  const names = ['entry.py', 'shop.entry']
  expect(namesEntry('{"command": "python ./entry.py"}', names)).toBe(true)
  expect(namesEntry('{"command": "python -m shop.entry"}', names)).toBe(true)
  expect(namesEntry('{"command": "python my_entry.py"}', names)).toBe(false)
  expect(namesEntry('{"command": "cat entry.pyc"}', names)).toBe(false)
  // The shell removes quotes and escapes, and expands a glob.
  for (const c of ['python entry\\.py', "python 'entr'y.py", 'python entr?.py', 'python e*.py']) {
    expect([c, namesEntry('{}', names, c)]).toEqual([c, true])
  }
  expect(namesEntry('{}', names, 'python other.py')).toBe(false)
})

test('during a test, the model cannot run the entry around the tap', { options: { start_on: true } }, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  f.files['.verbatim-relay/current.json'] = JSON.stringify(CURRENT)
  on('tool.call', async () => ({ result: 'ran' }))
  const run: any = await $.tool.call({ tool: 'Bash', command: 'cd examples/toy-shop && python agent.py' } as any)
  expect(run.deny).toBe('verbatim-relay: during a test, only the tap runs the entry.')
  const cat: any = await $.tool.call({ tool: 'Bash', command: 'cat examples/toy-shop/agent.py' } as any)
  expect(cat.deny).toBe(undefined)
  expect(rows(f.files[`${DIR}/relay.jsonl`]).map(r => r.tool)).toEqual(['Bash'])
})

test('after a test, a shell command that names the test files may only read', {}, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  on('tool.call', async () => ({ result: 'ran' }))
  const sed: any = await $.tool.call({ tool: 'Bash', command: `sed -i '' 's/4471/4417/' ${DIR}/trace.jsonl` } as any)
  expect(sed.deny).toContain('may only read')
  const mcp: any = await $.tool.call({ tool: 'mcp__files__write', path: `${DIR}/tap.jsonl` } as any)
  expect(typeof mcp.deny).toBe('string')
  const cat: any = await $.tool.call({ tool: 'Bash', command: `cat ${DIR}/trace.jsonl` } as any)
  expect(cat.deny).toBe(undefined)
  const report: any = await $.tool.call({ tool: 'Bash', command: `cat > ${DIR}/report.md <<'EOF'\n# Report\nEOF` } as any)
  expect(report.deny).toBe(undefined)
})

test('after a test, a deny goes to denied.jsonl and not to the sealed relay.jsonl', { options: { start_on: false } }, async ($, on) => {
  const f = fakes(on, contractReply)
  withTest(on, f)
  on('tool.call', async () => ({ result: 'ran' }))
  await $.command.run({ command: 'verbatim-relay', args: 'start' } as any)
  await $.command.run({ command: 'verbatim-relay', args: 'end' } as any)
  const relay = f.files[`${DIR}/relay.jsonl`]
  const sed: any = await $.tool.call({ tool: 'Bash', command: `sed -i '' 's/a/b/' ${DIR}/trace.jsonl` } as any)
  expect(typeof sed.deny).toBe('string')
  expect(rows(f.files[`${DIR}/denied.jsonl`]).map(r => r.tool)).toEqual(['Bash'])
  expect(f.files[`${DIR}/relay.jsonl`]).toBe(relay)
})
