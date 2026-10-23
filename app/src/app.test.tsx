import { act, render, screen } from "@testing-library/react";

import { Rich, actionText, stripStepPrefix } from "./lib/rich";
import { RpcClient, RpcError, type Transport } from "./rpc/client";
import { useApp } from "./stores/app";

class Loop implements Transport {
  sent: any[] = [];
  cb: (l: string) => void = () => {};
  async onLine(cb: (l: string) => void) {
    this.cb = cb;
    return () => {};
  }
  async send(line: string) {
    this.sent.push(JSON.parse(line));
  }
  push(obj: unknown) {
    this.cb(JSON.stringify(obj));
  }
}

const flush = () => new Promise((r) => setTimeout(r, 0));

test("rpc client matches replies by id, surfaces errors, dispatches notifications", async () => {
  const t = new Loop();
  const c = new RpcClient(t);
  const got: unknown[] = [];
  c.on("tutorial.progress", (p) => got.push(p));
  const a = c.call<{ x: number }>("a");
  const b = c.call("b");
  await flush();
  t.push({ jsonrpc: "2.0", id: t.sent[1].id, error: { code: -32001, message: "busy" } });
  t.push({ jsonrpc: "2.0", id: t.sent[0].id, result: { x: 1 } });
  t.push({ jsonrpc: "2.0", method: "tutorial.progress", params: { state: "ACT" } });
  c.receive("not json");
  expect(await a).toEqual({ x: 1 });
  await expect(b).rejects.toBeInstanceOf(RpcError);
  expect(got).toEqual([{ state: "ACT" }]);
});

test("store follows a demonstration from question to tutorial", async () => {
  const t = new Loop();
  const c = new RpcClient(t);
  useApp.getState().init(c);
  await flush();
  const asking = useApp.getState().ask("tạo pivot");
  await flush();
  const create = t.sent.find((m) => m.method === "tutorial.create");
  t.push({ jsonrpc: "2.0", id: create.id, result: { session_id: "s1" } });
  await asking;
  expect(useApp.getState().demo?.phase).toBe("planning");

  const prog = (p: object) => act(() => t.push({ jsonrpc: "2.0", method: "tutorial.progress", params: { session_id: "s1", ...p } }));
  prog({ state: "ACT", step_i: 1, n_steps: 3, intent: "select_ribbon_tab", label: "Insert" });
  expect(useApp.getState().demo?.current).toMatchObject({ n: 1, total: 3, label: "Insert" });
  prog({ state: "STEP_DONE", step_i: 1, n_steps: 3, intent: "select_ribbon_tab", label: "Insert", seconds: 4.2 });
  expect(useApp.getState().demo?.done).toEqual([{ n: 1, intent: "select_ribbon_tab", label: "Insert", seconds: 4.2 }]);
  prog({ state: "RECOVER", step_i: 2 });
  expect(useApp.getState().demo?.recovered).toBe(true);

  act(() => t.push({ jsonrpc: "2.0", method: "tutorial.done", params: { session_id: "s1", kind: "text", answer: "Không làm mẫu được." } }));
  expect(useApp.getState().demo).toBeNull();
  expect(useApp.getState().chat.at(-1)).toEqual({ kind: "answer", text: "Không làm mẫu được." });
});

test("bold labels render from engine markup", () => {
  render(<p><Rich text={"Nhấn **PivotTable** rồi **OK**"} /></p>);
  expect(screen.getByText("PivotTable").tagName).toBe("STRONG");
  expect(stripStepPrefix("Bước 12: Mở thẻ **Insert**")).toBe("Mở thẻ **Insert**");
  expect(actionText("select_ribbon_tab", "Insert")).toBe("Mở thẻ **Insert**");
  expect(actionText(undefined, undefined)).toBe("Đang tìm nút…");
});
