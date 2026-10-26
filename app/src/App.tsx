import { useEffect } from "react";

import { ChatColumn } from "./components/ChatColumn";
import { Consent } from "./components/Consent";
import { TutorialPane } from "./components/TutorialPane";
import { createClient, inTauri } from "./rpc/client";
import { useApp } from "./stores/app";

let started = false;

export default function App() {
  const consented = useApp((s) => s.consented);
  const demo = useApp((s) => s.demo);
  const cancel = useApp((s) => s.cancel);

  useEffect(() => {
    if (started) return; // StrictMode mounts twice in dev; one engine connection only
    started = true;
    useApp.getState().init(createClient());
  }, []);

  // Esc stops a running demonstration from anywhere in the app (SPEC §8).
  useEffect(() => {
    if (!demo) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [demo, cancel]);

  if (!consented) return <Consent />;

  return (
    <div className="grid h-full grid-cols-1 grid-rows-[auto_minmax(0,1fr)] min-[900px]:grid-cols-[360px_minmax(0,1fr)] min-[900px]:grid-rows-1">
      <ChatColumn />
      <TutorialPane />
      {!inTauri() && (
        <p className="no-print fixed bottom-2 right-3 rounded-sheet bg-ink px-2 py-1 text-small text-paper">
          Bản xem thử giao diện, không chạy Excel thật
        </p>
      )}
    </div>
  );
}
