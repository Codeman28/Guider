// Evaluate one JS expression in the running Guider webview (debug port 9333) and print the result.
//   node scripts/cdp-eval.mjs "<expression>"
const list = await (await fetch("http://127.0.0.1:9333/json")).json();
const ws = new WebSocket(list.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id === 1) {
    console.log(JSON.stringify(m.result?.result?.value ?? m.result, null, 1));
    ws.close();
  }
});
ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: process.argv[2], awaitPromise: true, returnByValue: true } }));
