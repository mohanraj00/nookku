// The TypeScript toy shop support agent: one Claude Agent SDK session with 3 tools, a stock
// service and a case-note model. It is the TypeScript form of examples/toy-shop-full/app.py.
//
// - The tools read the orders in state.json (or $TOY_SHOP_STATE), and call the stock service at
//   STOCK_URL.
// - After each reply, the app asks the note model at OPENAI_BASE_URL for a case note, and adds it
//   to state.json.
// - The shop's rules are in RULES.md.
//
// It needs the npm packages @anthropic-ai/claude-agent-sdk and zod, which are not dependencies of
// nookku. Node 23.6 or later runs this file with no build step: Node removes the types.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { createSdkMcpServer, query, tool } from "@anthropic-ai/claude-agent-sdk";
import type { Query, SDKMessage, SDKUserMessage } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";

import * as services from "./services.mts";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATE = process.env.TOY_SHOP_STATE ?? join(HERE, "state.json");
const SYSTEM =
  "You are the support agent of a toy shop. Use the tools for orders, stock and reservations. " +
  "Answer in 2 sentences or fewer.";

type State = { orders: Record<string, unknown>; notes?: string[] };

function load(): State {
  return JSON.parse(readFileSync(STATE, "utf-8"));
}

function save(state: State): void {
  writeFileSync(STATE, JSON.stringify(state, null, 1) + "\n", "utf-8");
}

function text(data: unknown, error = false) {
  const body = typeof data === "string" ? data : JSON.stringify(data);
  return { content: [{ type: "text" as const, text: body }], isError: error };
}

const lookupOrder = tool(
  "lookup_order",
  "Look up an order by its number",
  { order: z.string() },
  async (args) => {
    const order = load().orders[args.order];
    return order ? text(order) : text("no such order", true);
  },
);

const checkStock = tool(
  "check_stock",
  "The number of items left for a SKU, for example teapot-set",
  { sku: z.string() },
  async (args) => {
    const left = await services.stock(args.sku);
    return text(left, "error" in left);
  },
);

const reserve = tool(
  "reserve",
  "Reserve a number of items of a SKU for an order",
  { order: z.string(), sku: z.string(), qty: z.number().int() },
  async (args) => {
    const done = await services.reserve(args.order, args.sku, args.qty);
    if ("error" in done) return text(done.error, true);
    return text({ reservation: done.reservation, sku: args.sku, qty: args.qty });
  },
);

// The messages of the conversation, as the stream input of one model session.
class Inbox {
  queue: SDKUserMessage[] = [];
  wake: (() => void) | null = null;

  push(message: string): void {
    this.queue.push({
      type: "user",
      message: { role: "user", content: message },
      parent_tool_use_id: null,
    });
    this.wake?.();
  }

  async *messages(): AsyncGenerator<SDKUserMessage> {
    for (;;) {
      while (this.queue.length) yield this.queue.shift() as SDKUserMessage;
      await new Promise<void>((resolve) => (this.wake = resolve));
      this.wake = null;
    }
  }
}

// One model session for one conversation.
export class Shop {
  inbox = new Inbox();
  session: Query;

  constructor() {
    const tools = [lookupOrder, checkStock, reserve];
    // Load the 3 tools at the start. Without this, the model must first find each tool with
    // ToolSearch, and a small model can repeat that search.
    const server = createSdkMcpServer({ name: "shop", tools, alwaysLoad: true });
    this.session = query({
      prompt: this.inbox.messages(),
      options: {
        cwd: HERE,
        model: "haiku",
        systemPrompt: SYSTEM,
        mcpServers: { shop: server },
        allowedTools: tools.map((t) => `mcp__shop__${t.name}`),
        // Isolate the session from the machine of the tester: no settings files, only the
        // shop's MCP server (no claude.ai connectors), and no plugins from
        // CLAUDE_CODE_PLUGIN_DIRS. The value of env replaces the environment of the session, so
        // it starts from process.env: the session needs ANTHROPIC_BASE_URL of the test.
        settingSources: [],
        strictMcpConfig: true,
        env: { ...process.env, ENABLE_TOOL_SEARCH: "false", CLAUDE_CODE_PLUGIN_DIRS: "" },
      },
    });
  }

  close(): void {
    this.session.close();
  }

  async reply(message: string): Promise<string> {
    this.inbox.push(message);
    let answer = "";
    for (;;) {
      const next: IteratorResult<SDKMessage> = await this.session.next();
      if (next.done) throw new Error("the model session ended");
      if (next.value.type === "result") {
        answer = next.value.subtype === "success" ? next.value.result : "";
        break;
      }
    }
    const state = load();
    const note = await services.caseNote(message, answer);
    (state.notes ??= []).push(`${await services.department(message)}: ${note}`);
    save(state);
    return answer;
  }
}
