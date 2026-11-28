// The calls of the TypeScript toy shop to its stock service and to its case-note model.
//
// The stock service URL is in STOCK_URL. The note model speaks the OpenAI Chat Completions API
// and the OpenAI Decisions API at OPENAI_BASE_URL. It uses only the fetch of Node.

const NOTE_MODEL = "toy-notes";

type Answer = Record<string, unknown>;

async function call(method: string, url: string, body?: unknown): Promise<[number, Answer]> {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  });
  const text = await response.text();
  return [response.status, text ? (JSON.parse(text) as Answer) : {}];
}

function stockUrl(): string {
  return (process.env.STOCK_URL ?? "http://127.0.0.1:9001").replace(/\/+$/, "");
}

function modelUrl(): string {
  return (process.env.OPENAI_BASE_URL ?? "https://api.openai.com/v1").replace(/\/+$/, "");
}

function modelHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${process.env.OPENAI_API_KEY ?? "toy"}`,
  };
}

// The number of items left for a SKU.
export async function stock(sku: string): Promise<Answer> {
  const [status, data] = await call("GET", `${stockUrl()}/stock?sku=${encodeURIComponent(sku)}`);
  return status === 200 ? data : { error: data.error ?? `status ${status}` };
}

// Reserve items for an order. A slow stock service can lose a request, so try 2 times.
export async function reserve(order: string, sku: string, qty: number): Promise<Answer> {
  let answer: Answer = { error: "the stock service did not answer" };
  const ask = { order, sku, qty };
  for (let i = 0; i < 2; i++) {
    const [status, data] = await call("POST", `${stockUrl()}/reserve`, ask);
    if (status === 200) {
      answer = data;
    } else if (!("reservation" in answer)) {
      answer = { error: data.error ?? `status ${status}` };
    }
  }
  return answer;
}

// A one-line case note for the shop's log, from the note model, as a stream.
export async function caseNote(message: string, reply: string): Promise<string> {
  const response = await fetch(`${modelUrl()}/chat/completions`, {
    method: "POST",
    headers: modelHeaders(),
    body: JSON.stringify({
      model: NOTE_MODEL,
      stream: true,
      messages: [
        { role: "system", content: "Write a one-line case note." },
        { role: "user", content: `Customer: ${message}\nAgent: ${reply}` },
      ],
    }),
    signal: AbortSignal.timeout(30_000),
  });
  let text = "";
  for (const line of (await response.text()).split("\n")) {
    if (line.startsWith("data: ") && line !== "data: [DONE]") {
      for (const choice of JSON.parse(line.slice(6)).choices ?? []) {
        text += choice.delta?.content ?? "";
      }
    }
  }
  return text;
}

const DEPARTMENTS = [
  { value: "billing", description: "Payments, invoices and refunds." },
  { value: "shipping", description: "Delivery, and items that arrived broken." },
  { value: "other", description: "Requests outside these departments." },
];

// The department for a complaint, from a `choice` question to the Decisions API.
export async function department(message: string): Promise<string> {
  const response = await fetch(`${modelUrl()}/decisions`, {
    method: "POST",
    headers: modelHeaders(),
    body: JSON.stringify({
      model: NOTE_MODEL,
      input: message,
      questions: [
        {
          type: "choice",
          name: "department",
          instructions: "Which department should handle this complaint?",
          choices: DEPARTMENTS,
        },
      ],
    }),
    signal: AbortSignal.timeout(30_000),
  });
  const answer = (await response.json()).answers[0];
  return answer.type === "choice" ? String(answer.choice) : "other";
}
