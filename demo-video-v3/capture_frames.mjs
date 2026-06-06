import { writeFile } from "node:fs/promises";

const root = new URL(".", import.meta.url).pathname;
const targets = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = targets.find((target) => target.type === "page");

if (!page) {
  throw new Error("No Chrome page target found.");
}

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
  return command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
}

async function clickButton(label) {
  const result = await evaluate(`(() => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => item.innerText.trim().replace(/\\s+/g, " ").includes(${JSON.stringify(label)})
    );
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!result.result.value) throw new Error(`Button not found: ${label}`);
}

async function capture(fileName) {
  const result = await command("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  await writeFile(`${root}frames/${fileName}`, Buffer.from(result.data, "base64"));
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
await sleep(1200);
await capture("01-home.png");

await clickButton("Why did checkout freeze during the holiday sale?");
await sleep(1600);
await capture("02-answer.png");

await clickButton("INC-001");
await sleep(500);
await capture("03-source.png");

await clickButton("Ask EchoMind");
await sleep(400);
await clickButton("Who knows StockSync inventory reservations?");
await sleep(1600);
await capture("04-expert.png");

await clickButton("How did CheckoutFlow evolve?");
await sleep(1600);
await capture("05-timeline.png");

await clickButton("Company Memory");
await sleep(600);
await capture("06-memory.png");

await clickButton("Open a connected project workspace");
await sleep(600);
await capture("07-project.png");

socket.close();
console.log("Captured seven lossless 1920x1080 frames.");
