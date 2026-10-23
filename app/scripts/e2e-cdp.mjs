// End-to-end check of the real app: drives the Tauri WebView2 over the Chrome DevTools Protocol.
//   set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333 and start guider.exe, then
//   node scripts/e2e-cdp.mjs [question]
// Clicks through consent → machine check → asks → waits for the tutorial; screenshots to engine/.out/e2e.
// The machine must be left alone while it runs (Office closes menus when focus moves — ADR-0001).
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const PORT = 9333;
const OUT = resolve(import.meta.dirname, "../../engine/.out/e2e");
const QUESTION = process.argv[2] ?? "Làm sao tạo PivotTable tổng hợp doanh số?";
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error("no WebView2 debug target — was guider.exe started with the debugging port?");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const waiting = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && waiting.has(m.id)) {
    waiting.get(m.id)(m);
    waiting.delete(m.id);
  }
});
const cdp = (method, params = {}) =>
  new Promise((r) => {
    const i = ++id;
    waiting.set(i, r);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
const js = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value;
const text = () => js("document.body.innerText");
async function shot(name) {
  const r = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(resolve(OUT, `${name}.png`), Buffer.from(r.result.data, "base64"));
  console.log("screenshot", name);
}
async function click(label) {
  const ok = await js(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === ${JSON.stringify(label)}); if (!b || b.disabled) return false; b.click(); return true; })()`);
  if (!ok) throw new Error(`button not found/enabled: ${label}`);
  console.log("click", label);
}
async function until(pred, what, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (await js(pred)) return;
    await sleep(1000);
  }
  throw new Error(`timeout waiting for ${what}`);
}

const t0 = Date.now();
const has = (s) => `document.body.innerText.includes(${JSON.stringify(s)})`;

// CAPTURE=1: no demonstration; open the newest tutorial from the library and capture the review set
// into .impeccable/review/ (desktop, narrow, steps mode, consent).
if (process.env.CAPTURE) {
  const REV = resolve(import.meta.dirname, "../../.impeccable/review");
  mkdirSync(REV, { recursive: true });
  const save = async (name) => {
    await sleep(800);
    const r = await cdp("Page.captureScreenshot", { format: "png" });
    writeFileSync(resolve(REV, `${name}.png`), Buffer.from(r.result.data, "base64"));
    console.log("review", name);
  };
  await js(`localStorage.setItem('guider.consent.v1','yes')`);
  await js(`location.reload()`);
  await sleep(3000);
  await until(`!!document.querySelector('section[aria-label="Thư viện hướng dẫn"] button')`, "library", 30000);
  await save("empty");
  await js(`document.querySelector('section[aria-label="Thư viện hướng dẫn"] button').click()`);
  await until(`document.querySelectorAll('article img').length > 0`, "tutorial", 20000);
  await save("desktop");
  if (await js(`[...document.querySelectorAll('article section')].length > 0`)) {
    await js(`(() => { const s = [...document.querySelectorAll('article section')].at(-1); const p = s.closest('[role=tabpanel]'); p.scrollTop = s.offsetTop - 16; })()`);
    await save("last-step");
    await js(`document.querySelector('article').closest('[role=tabpanel]').scrollTop = 0`);
  }
  await click("Từng bước");
  await save("steps");
  await click("Xem Guider đã làm gì");
  await save("trace");
  await cdp("Emulation.setDeviceMetricsOverride", { width: 720, height: 900, deviceScaleFactor: 1, mobile: false });
  await save("user-720");
  await cdp("Emulation.clearDeviceMetricsOverride");
  await js(`localStorage.removeItem('guider.consent.v1')`);
  await js(`location.reload()`);
  await sleep(3000);
  await save("consent");
  await js(`localStorage.setItem('guider.consent.v1','yes')`);
  ws.close();
  process.exit(0);
}
await until(`document.body.innerText.length > 20`, "first render", 30000);
await shot("01-start");

if ((await text()).includes("Đồng ý và kiểm tra máy")) {
  await click("Đồng ý và kiểm tra máy");
  await until(`${has("Bắt đầu")} || ${has("Kiểm tra lại")}`, "machine check", 180000);
  await shot("02-check");
  if (!(await text()).includes("Bắt đầu")) throw new Error("machine check failed:\n" + (await text()));
  await click("Bắt đầu");
}

await until(`!!document.querySelector('#ask')`, "chat", 10000);
await js(`(() => { const t = document.querySelector('#ask'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set; set.call(t, ${JSON.stringify(QUESTION)}); t.dispatchEvent(new Event('input', {bubbles:true})); })()`);
await click("Hỏi");
await until(`${has("BƯỚC")} && ${has("TRÊN")}`, "demonstration progress", 240000);
await sleep(1500);
await shot("03-demonstrating");
await until(`${has("Mở hướng dẫn")} || document.querySelectorAll('article').length > 0 || ${has("Guider chưa")}`, "result", 600000);
await sleep(2500);
await shot("04-tutorial");

const imgs = await js(`[...document.querySelectorAll('article img')].map(i => ({w: i.naturalWidth, src: i.src.slice(0, 60)}))`);
const summary = { seconds: Math.round((Date.now() - t0) / 1000), images: imgs, broken: (imgs || []).filter((i) => !i.w).length, text: (await text()).slice(0, 600) };
writeFileSync(resolve(OUT, "summary.json"), JSON.stringify(summary, null, 2));
console.log(JSON.stringify({ seconds: summary.seconds, images: imgs?.length, broken: summary.broken }));
ws.close();
