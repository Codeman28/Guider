import { useEffect, useState } from "react";

import { useApp } from "../stores/app";

/** Images (tutorial screenshots, attached pictures) as data URLs from the engine. Tauri's asset protocol
 *  answered 403 for files inside its scope on the installed build (10/11/2026), so the UI no longer uses it.
 *  Each image is fetched once per session and kept in memory. */
const cache = new Map<string, Promise<string>>();

export function useImage(method: "tutorial.image" | "problem.image", params: Record<string, string>): string {
  const client = useApp((s) => s.client);
  const key = method + JSON.stringify(params);
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!client) return;
    let live = true;
    let p = cache.get(key);
    if (!p) {
      p = client.call<{ data_url: string }>(method, params).then((r) => r.data_url);
      p.catch(() => cache.delete(key)); // retry next time (e.g. the engine was restarting)
      cache.set(key, p);
    }
    p.then((u) => live && setUrl(u)).catch(() => live && setUrl(""));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, key]);
  return url;
}
