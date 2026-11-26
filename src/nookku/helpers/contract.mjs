import { promisify, types } from "node:util";

// Keep stdout for contract lines. Send app output to stderr from the time of import.
const writeLine = promisify(process.stdout.write.bind(process.stdout));
process.stdout.write = process.stderr.write.bind(process.stderr);

const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });

function invalidJsonReason(line) {
  const tokens = /"(?:[^"\\]|\\[\s\S])*"?|([{\[])|[}\]]|(NaN|-?Infinity)/g;
  const closing = [];
  for (const match of line.matchAll(tokens)) {
    const [token, open, constant] = match;
    if (open) {
      closing.push(open === "{" ? "}" : "]");
    } else if (token === "}" || token === "]") {
      closing.pop();
    } else if (constant) {
      // Check if the text before the constant allows a value at this position.
      try {
        JSON.parse(line.slice(0, match.index) + "null" + closing.reverse().join(""));
      } catch { // The JSON error occurs before the constant.
        break;
      }
      return `${constant} is not a JSON value`;
    }
  }
  return "the request is not UTF-8 JSON";
}

function parseRequest(raw) {
  if (raw[raw.length - 1] === 0x0d) raw = raw.subarray(0, -1);
  if (raw.includes(0x0d)) throw new SyntaxError("the request has a raw line end");

  let line;
  try {
    line = decoder.decode(raw);
  } catch { // Report invalid UTF-8 as a contract error.
    throw new SyntaxError("the request is not UTF-8 JSON");
  }
  let request;
  try {
    request = JSON.parse(line);
  } catch { // Report invalid JSON as a contract error.
    throw new SyntaxError(invalidJsonReason(line));
  }
  if (request === null || typeof request !== "object" || Array.isArray(request)) {
    throw new SyntaxError("the request is not a JSON object");
  }
  if (request.v !== 1) throw new SyntaxError("the request is not contract version 1");
  if (typeof request.id !== "string") throw new SyntaxError("the request has no string 'id'");
  if (typeof request.session !== "string" || typeof request.message !== "string") {
    throw new SyntaxError("the request needs a string 'session' and a string 'message'");
  }
  if (!Array.isArray(request.history)) throw new SyntaxError("the request 'history' is not a list");
  if (
    !request.history.every(
      (turn) => typeof turn?.message === "string" && typeof turn.reply === "string",
    )
  ) {
    throw new SyntaxError("each history turn needs a string 'message' and 'reply'");
  }
  return request;
}

function errorMessage(error) {
  try {
    if (types.isNativeError(error)) return `${error.name}: ${error.message}`;
    return String(error?.message ?? error);
  } catch { // Some thrown values cannot convert to text.
    return "The app failed.";
  }
}

async function answer(line, reply) {
  let request;
  try {
    request = parseRequest(line);
  } catch (error) { // Send the request error to the tester and continue.
    if (!(error instanceof SyntaxError)) throw error;
    const output = { v: 1, id: "", error: `nookku agent: ${error.message}` };
    await writeLine(JSON.stringify(output) + "\n", "utf8");
    return;
  }

  const output = { v: 1, id: request.id };
  try {
    const text = await reply(request.message, request.history);
    if (typeof text !== "string") throw new TypeError("reply() must return a string");
    output.reply = text;
  } catch (error) { // Send the app error to the tester and continue.
    output.error = errorMessage(error);
  }
  await writeLine(JSON.stringify(output) + "\n", "utf8");
}

/**
 * Read requests from stdin until it closes. Write one line for each request.
 * @param {(message: string, history: {message: string, reply: string}[]) => string | Promise<string>} reply
 */
export async function serve(reply) {
  // Split only at LF. Decode UTF-8 after all bytes of the line arrive.
  let pending = [];
  for await (const chunk of process.stdin) {
    let start = 0;
    let end = chunk.indexOf(0x0a);
    while (end !== -1) {
      const part = chunk.subarray(start, end);
      const line = pending.length ? Buffer.concat([...pending, part]) : part;
      pending = [];
      await answer(line, reply);
      start = end + 1;
      end = chunk.indexOf(0x0a, start);
    }
    if (start < chunk.length) pending.push(chunk.subarray(start));
  }
  if (pending.length) await answer(Buffer.concat(pending), reply);
}
