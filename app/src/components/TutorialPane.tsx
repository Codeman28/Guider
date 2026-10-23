import * as Tabs from "@radix-ui/react-tabs";

import { useApp } from "../stores/app";
import { Library } from "./Library";
import { TutorialView } from "./TutorialView";

export function TutorialPane() {
  const { tabs, active, setActive, close, tutorials, notice } = useApp();

  return (
    <main className="flex min-h-0 flex-col bg-shell">
      <Tabs.Root value={active ?? "library"} onValueChange={(v) => setActive(v === "library" ? null : v)} className="flex min-h-0 flex-1 flex-col">
        <Tabs.List aria-label="Hướng dẫn đã mở" className="no-print flex h-14 flex-none items-end gap-1 overflow-x-auto px-6">
          <Tabs.Trigger value="library" className="rounded-t-sheet px-4 py-2.5 text-sm text-ink data-[state=active]:border-t-4 data-[state=active]:border-glue data-[state=active]:bg-paper data-[state=active]:font-medium data-[state=inactive]:bg-edge">
            Thư viện
          </Tabs.Trigger>
          {tabs.map((t) => (
            <div key={t.id} className="flex items-stretch">
              <Tabs.Trigger value={t.id} className="max-w-[240px] truncate rounded-tl-sheet px-4 py-2.5 text-sm data-[state=active]:border-t-4 data-[state=active]:border-glue data-[state=active]:bg-paper data-[state=active]:font-medium data-[state=inactive]:bg-edge">
                {t.title}
              </Tabs.Trigger>
              <button type="button" aria-label={`Đóng ${t.title}`} onClick={() => close(t.id)} className={`rounded-tr-sheet px-2 text-sm ${active === t.id ? "border-t-4 border-glue bg-paper" : "bg-edge"}`}>
                ×
              </button>
            </div>
          ))}
        </Tabs.List>
        <Tabs.Content value="library" className="min-h-0 flex-1 overflow-y-auto bg-paper">
          <Library />
        </Tabs.Content>
        {tabs.map((t) => (
          <Tabs.Content key={t.id} value={t.id} className="min-h-0 flex-1 overflow-y-auto bg-paper">
            {tutorials[t.id] && <TutorialView t={tutorials[t.id]} />}
          </Tabs.Content>
        ))}
      </Tabs.Root>
      {notice && (
        <p role="status" className="no-print flex-none border-t border-edge bg-white px-6 py-2 text-sm text-lunar">
          {notice}
        </p>
      )}
    </main>
  );
}
