"use client";
// Staff-only Ask Overwatch (ADR 0004). The passcode is entered once per browser;
// a 401 forgets it. Answers come from the read-only agent and are never actions.
import { FormEvent, useEffect, useState } from "react";
import { askOverwatch, isTrustedApi, loadStaffKey, saveStaffKey } from "@/lib/agent";
import { theme } from "@/lib/theme";

export function AskOverwatch({ api, live }: { api: string; live: boolean }) {
  const [key, setKey] = useState("");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<{ q: string; text: string; seconds: number } | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => { setKey(loadStaffKey()); }, []);

  if (!live || !api || !isTrustedApi(api)) {
    return (
      <form className="ask panel" onSubmit={(e) => e.preventDefault()}>
        <label htmlFor="ask" className="title">Ask overwatch</label>
        <input id="ask" placeholder="e.g. Which joint is running hottest, and why?" disabled aria-describedby="ask-note" />
        <span id="ask-note" className="muted">{api && !isTrustedApi(api) ? "Asking is off for a custom API." : `Live data only. The agent runs on ${theme.agentHost}.`}</span>
      </form>
    );
  }

  if (!key) {
    const unlock = (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const v = String(new FormData(e.currentTarget).get("passcode") ?? "").trim();
      if (v) { saveStaffKey(v); setKey(v); setNote(""); }
    };
    return (
      <form className="ask panel" onSubmit={unlock}>
        <label htmlFor="passcode" className="title">Ask overwatch</label>
        <input id="passcode" name="passcode" type="password" autoComplete="off" placeholder="Staff passcode" aria-describedby="ask-note" />
        <span id="ask-note" className={note ? "note warning" : "muted"}>{note || "Staff only. Entered once on this device."}</span>
      </form>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const question = q.trim().slice(0, 500);
    if (!question || busy) return;
    setBusy(true); setNote("");
    const r = await askOverwatch(api, key, question);
    setBusy(false);
    if (r.ok) { setAnswer({ q: question, text: r.text, seconds: r.seconds }); setQ(""); return; }
    if (r.status === 401) { saveStaffKey(""); setKey(""); setNote("Passcode not accepted. Enter it again."); return; }
    setNote(r.status === 0 ? "Can't reach the agent. Check the booth connection." : `Agent unavailable (${r.message}).`);
  };

  return (
    <form className="ask panel" onSubmit={submit} aria-busy={busy}>
      <label htmlFor="ask" className="title">Ask overwatch</label>
      <input id="ask" value={q} onChange={(e) => setQ(e.target.value)} maxLength={500} disabled={busy}
        placeholder="e.g. Which joint is running hottest, and why?" aria-describedby="ask-note" />
      <span id="ask-note" className={note ? "note warning" : "muted"}>{busy ? "Asking…" : note || `Read-only agent on ${theme.agentHost}.`}</span>
      {answer && (
        <div className="ask-answer" aria-live="polite">
          <span className="muted">{answer.q}</span>
          <p>{answer.text}</p>
        </div>
      )}
    </form>
  );
}
