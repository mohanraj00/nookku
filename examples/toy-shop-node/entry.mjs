// The toy shop agent in Node, as the entry of a nooku test (SPEC.md section 6).
// It reads one JSON line on stdin for each message, and writes one JSON line on stdout.
// Usage: node examples/toy-shop-node/entry.mjs

// Stdout is only for contract lines. Send the console.log output of the app to stderr.
console.log = console.error;

// The app. Replace this function with the call to your own app.
const REPLIES = {
  refund: "Our refund policy:\n\n1. Damaged items: full refund.\n2. Change of mind: 30 days.\n",
  ship: "We ship to Chennai and Pune. Delivery takes 3 to 5 days.  ",
};

async function reply(message, history) {
  if (message.includes("order")) throw new Error("the order service is down");
  const key = Object.keys(REPLIES).find((k) => message.toLowerCase().includes(k));
  return key ? REPLIES[key] : "Which item is this about: the mug or the teapot?";
}

async function answer(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (err) {
    console.error(`toy shop agent: not a contract line: ${err.message}`);
    return;
  }
  const out = { v: 1, id: request.id };
  try {
    out.reply = await reply(request.message, request.history);
  } catch (err) {
    out.error = String(err?.message ?? err);
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}

console.error("toy shop agent: ready");
// Split the input only at "\n". node:readline also splits at "\r", and in Node 25 also at
// U+2028 and U+2029. A message can contain U+2028.
process.stdin.setEncoding("utf8");
let pending = "";
for await (const chunk of process.stdin) {
  const lines = (pending + chunk).split("\n");
  pending = lines.pop();
  for (const line of lines) await answer(line);
}
