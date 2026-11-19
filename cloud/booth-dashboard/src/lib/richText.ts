// The agent sometimes answers in light Markdown ("**FR hip** is warm"). The dashboard
// draws plain text, so the markers used to show as literal asterisks. This turns bold
// into segments a component can render and drops the other inline markers.
// Kept free of imports so `node --test scripts/richtext.test.mjs` can load it directly.

export interface Segment { text: string; bold: boolean }

/** Splits agent text into plain and bold runs. `**x**` and `__x__` become bold; a stray
 *  unpaired `**`, `*emphasis*`, `` `code` `` and leading `#` heading marks are removed.
 *  Single underscores are left alone: joint names such as FR_hip use them. */
export function splitBold(text: string): Segment[] {
  if (!text) return [];
  const clean = text
    .replace(/^[ \t]*#{1,6}[ \t]+/gm, "")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/(?<![*\w])\*(?![*\s])([^*\n]+?)(?<![*\s])\*(?![*\w])/g, "$1");
  const out: Segment[] = [];
  const push = (t: string, bold: boolean) => {
    const s = t.replace(/\*\*|(?<!\w)__|__(?!\w)/g, "");
    if (!s) return;
    const last = out[out.length - 1];
    if (last && last.bold === bold) last.text += s; else out.push({ text: s, bold });
  };
  const re = /\*\*(?!\s)([^\n]+?)(?<!\s)\*\*|(?<!\w)__(?!\s)([^\n]+?)(?<!\s)__(?!\w)/g;
  let at = 0;
  for (let m = re.exec(clean); m; m = re.exec(clean)) {
    push(clean.slice(at, m.index), false);
    push(m[1] ?? m[2], true);
    at = m.index + m[0].length;
  }
  push(clean.slice(at), false);
  return out;
}

/** The same text with every marker removed, for labels that cannot hold markup. */
export const plainText = (text: string): string => splitBold(text).map((s) => s.text).join("");
