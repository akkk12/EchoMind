import { writeFile } from "node:fs/promises";

const output = new URL("./screenshots/", import.meta.url).pathname;
const targets = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = targets.find((target) => target.type === "page");

if (!page) throw new Error("No Chrome page target found.");

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 1;
const pending = new Map();

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function command(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  return result.result?.value;
}

async function click(label) {
  const found = await evaluate(`(() => {
    const label = ${JSON.stringify(label)};
    const element = [...document.querySelectorAll("button, a, [role='button']")]
      .find((item) => item.innerText.trim().replace(/\\s+/g, " ").includes(label));
    if (!element) return false;
    element.click();
    return true;
  })()`);
  if (!found) throw new Error(`Could not find: ${label}`);
}

async function capture(name) {
  const result = await command("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  await writeFile(`${output}${name}`, Buffer.from(result.data, "base64"));
}

await command("Page.enable");
await command("Runtime.enable");
await command("Emulation.setDeviceMetricsOverride", {
  width: 1920,
  height: 1080,
  deviceScaleFactor: 1,
  mobile: false,
});
await command("Page.navigate", { url: "http://localhost:5173/" });
await sleep(1400);
await capture("ask-echomind.png");

await click("Why did checkout freeze during the holiday sale?");
await sleep(1800);
await capture("evidence-backed-answer.png");

await click("INC-001");
await sleep(700);
await capture("traceable-source.png");

await click("Company Memory");
await sleep(900);
await capture("company-memory.png");

socket.close();
console.log("Captured four lossless README screenshots.");
