// Debug helper: load one asset URL in the running Guider webview (debug port 9333) and print the network result.
//   node scripts/cdp-net.mjs "<absolute file path>"
const list = await (await fetch("http://127.0.0.1:9333/json")).json();
const ws = new WebSocket(list.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const send = (method, params = {}) => ws.send(JSON.stringify({ id: ++id, method, params }));
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.method === "Network.responseReceived" && m.params.response.url.includes("asset.localhost"))
    console.log("response", m.params.response.status, m.params.response.statusText, JSON.stringify(m.params.response.headers));
  if (m.method === "Network.loadingFailed") console.log("failed", m.params.errorText, m.params.blockedReason ?? "");
});
send("Network.enable");
const url = "http://asset.localhost/" + encodeURIComponent(process.argv[2]);
send("Runtime.evaluate", { expression: `(()=>{const i=new Image();i.src=${JSON.stringify(url)};document.body.appendChild(i);setTimeout(()=>i.remove(),3000)})()` });
setTimeout(() => ws.close(), 3000);
