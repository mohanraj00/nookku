// The toy shop agent in Node, as the entry of a nookku test (SPEC.md section 6).
// It reads one JSON line on stdin for each message, and writes one JSON line on stdout.
// Usage: node examples/toy-shop-node/entry.mjs

import { serve } from "./contract.mjs";

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

console.error("toy shop agent: ready");
await serve(reply);
