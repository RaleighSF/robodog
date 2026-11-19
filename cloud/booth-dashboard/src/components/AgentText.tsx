// Agent-written prose for display: Celsius rewritten to °F, Markdown bold rendered,
// other markers dropped. React escapes the text, so nothing here is treated as HTML.
import { splitBold } from "@/lib/richText";
import { showTempText } from "@/lib/temp";

export function AgentText({ text }: { text: string }) {
  return <>{splitBold(showTempText(text)).map((s, i) => (s.bold ? <strong key={i}>{s.text}</strong> : s.text))}</>;
}
