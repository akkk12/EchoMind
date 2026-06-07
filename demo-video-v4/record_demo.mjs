import { mkdir, writeFile } from "node:fs/promises";

const root = new URL(".", import.meta.url).pathname;
const framesDir = `${root}frames`;
const fps = 8;
const frameInterval = 1000 / fps;
const outputSeconds = 94.955;

await mkdir(framesDir, { recursive: true });

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
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text);
  }
  return result.result?.value;
}

async function clickByText(label) {
  let clicked = false;
  for (let attempt = 0; attempt < 16; attempt += 1) {
    clicked = await evaluate(`(() => {
      const text = ${JSON.stringify(label)};
      const candidates = [...document.querySelectorAll("button, a, [role='button']")];
      const element = candidates.find((item) =>
        item.innerText.trim().replace(/\\s+/g, " ").includes(text)
      );
      if (!element) return false;
      element.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
      setTimeout(() => element.click(), 250);
      return true;
    })()`);
    if (clicked) break;
    await sleep(350);
  }
  if (!clicked) throw new Error(`Clickable element not found: ${label}`);
  await sleep(650);
}

async function submitQuestion() {
  const submitted = await evaluate(`(() => {
    const input = document.querySelector("main input, main textarea");
    if (!input) return false;
    const container = input.closest("div");
    const button = container?.querySelector("button") ||
      [...document.querySelectorAll("main button")].find((item) =>
        item.innerText.trim().replace(/\\s+/g, " ").includes("Ask EchoMind")
      );
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!submitted) throw new Error("Question submit button not found.");
  await sleep(650);
}

async function typeQuestion(question) {
  await evaluate(`(() => {
    const input = document.querySelector("input, textarea");
    if (!input) return false;
    input.focus();
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await sleep(250);

  for (const char of question) {
    await evaluate(`(() => {
      const input = document.querySelector("input, textarea");
      input.value += ${JSON.stringify(char)};
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(char === " " ? 20 : 34);
  }
}

async function ask(question) {
  await typeQuestion(question);
  await sleep(250);
  await submitQuestion();
  await sleep(1700);
}

async function smoothScroll(amount, steps = 16) {
  const step = amount / steps;
  for (let index = 0; index < steps; index += 1) {
    await evaluate(`window.scrollBy({ top: ${step}, behavior: "smooth" })`);
    await sleep(90);
  }
}

async function captureLoop() {
  const totalFrames = Math.ceil(outputSeconds * fps);
  let frame = 1;
  let nextCapture = Date.now();

  while (frame <= totalFrames) {
    const result = await command("Page.captureScreenshot", {
      format: "jpeg",
      quality: 93,
      fromSurface: true,
      captureBeyondViewport: false,
    });
    const name = String(frame).padStart(5, "0");
    await writeFile(`${framesDir}/${name}.jpg`, Buffer.from(result.data, "base64"));
    frame += 1;

    nextCapture += frameInterval;
    const wait = nextCapture - Date.now();
    if (wait > 0) await sleep(wait);
  }
}

async function performDemo() {
  const startedAt = Date.now();
  const waitUntil = async (milliseconds) => {
    const wait = milliseconds - (Date.now() - startedAt);
    if (wait > 0) await sleep(wait);
  };

  await waitUntil(12800);
  await ask("Why did checkout freeze during the holiday sale?");
  await waitUntil(28500);
  await smoothScroll(250, 8);
  await waitUntil(40500);
  await clickByText("INC-001");
  await waitUntil(46200);
  await clickByText("Back");

  await waitUntil(46800);
  await clickByText("Ask EchoMind");
  await sleep(250);
  await ask("Who knows StockSync inventory reservations?");
  await waitUntil(58100);
  await smoothScroll(360, 8);

  await waitUntil(59000);
  await ask("How did CheckoutFlow evolve?");
  await waitUntil(66500);
  await smoothScroll(500, 12);

  await waitUntil(69000);
  await clickByText("Company Memory");
  await waitUntil(76000);
  await smoothScroll(500, 12);
  await waitUntil(82500);
  await smoothScroll(650, 14);
  await waitUntil(86000);
  await clickByText("Open a connected project workspace");
  await waitUntil(91500);
  await smoothScroll(400, 10);
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
await sleep(2200);

await Promise.all([captureLoop(), performDemo()]);
socket.close();

console.log(`Recorded ${Math.ceil(outputSeconds * fps)} moving demo frames at ${fps} fps.`);
