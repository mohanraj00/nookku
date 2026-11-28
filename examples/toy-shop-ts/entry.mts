// The entry of the TypeScript toy shop: agent contract v1 on stdin and stdout (SPEC.md section 6).
//
// It uses contract.mjs, the Node helper of the nookku package. Copy the helper next to this file
// first (README.md). Import the helper before the app: from the time of import, it sends console
// output to stderr (app.log), and only contract lines go to stdout.

import { serve } from "./contract.mjs";

const { Shop } = await import("./app.mts");

const shop = new Shop();
console.error("toy shop agent: ready");
try {
  await serve((message: string) => shop.reply(message));
} finally {
  shop.close();
}
