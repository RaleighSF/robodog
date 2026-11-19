// Display-only Fahrenheit. Telemetry, LIMITS, the dial span and the trend-tape
// geometry stay in °C; convert only where a number is drawn for a person.
// Kept free of imports so `node --test scripts/temp.test.mjs` can load it directly.

export const TEMP_UNIT = "°F";

export const cToF = (c: number): number => c * 1.8 + 32;

/** A Celsius reading as whole degrees Fahrenheit, or "--" when there is no valid reading. */
export function showTemp(c: number | null | undefined): string {
  return c == null || !Number.isFinite(c) ? "--" : cToF(c).toFixed(0);
}

const decimals = (s: string) => (s.split(".")[1] ?? "").length;
/** A difference or a rate: scale only, no 32 offset; keeps the precision it was written with. */
const scaled = (num: string) => (Number(num) * 1.8).toFixed(decimals(num));

// 1-3: optional range start ("33–", "5-", "−10 to "), 4-6: the reading and its space,
// 7: "/" when it is a rate (°C/min). 8-9: a signed bare-degree change ("+1° in 10 min").
const CELSIUS = /(?<![\w.])(?:([+\-−]?)(\d+(?:\.\d+)?)(\s?–\s?|-|\s+to\s+))?([+\-−]?)(\d+(?:\.\d+)?)([ \u00a0\u202f]?)°C\b(\/)?|([+\-−])(\d+(?:\.\d+)?)°(?=\s+in\s+\d)/g;
const DEGREES_C = /(\d+(?:\.\d+)?)(\s+degrees?\s+)(C\b|Celsius\b)/g;

/** Rewrites Celsius in server- and agent-written text for display: readings ("56 °C"),
 *  ranges ("33–42 °C"), rates ("3.0 °C/min") and changes ("+1° in 10 min"). A leading
 *  "+" marks a change (scaled only); a leading minus is a reading below zero. Angles
 *  ("tilt 34°") and text already in °F pass through untouched. */
export function showTempText(text: string): string {
  if (!text) return text;
  return text
    .replace(CELSIUS, (_m, s1, n1, sep, s2, n2, sp, rate, ds, dn) => {
      if (dn !== undefined) return `${ds}${scaled(dn)}°`;
      const one = (sign: string, num: string) => {
        if (rate || sign === "+") return `${sign}${scaled(num)}`;
        const f = Math.round(cToF(sign ? -Number(num) : Number(num)));
        return f < 0 ? `${sign || "−"}${-f}` : String(f);
      };
      return `${n1 !== undefined ? one(s1, n1) + sep : ""}${one(s2, n2)}${sp}${TEMP_UNIT}${rate ?? ""}`;
    })
    .replace(DEGREES_C, (_m, n, mid, unit) => `${showTemp(Number(n))}${mid}${unit === "C" ? "F" : "Fahrenheit"}`);
}
