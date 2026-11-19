// Agent text: Markdown bold is rendered, stray markers never reach the screen.
// Run: node --test scripts/richtext.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { plainText, splitBold } from "../src/lib/richText.ts";

const seg = (text, bold = false) => ({ text, bold });

test("bold runs are split out", () => {
  assert.deepEqual(splitBold("**All systems nominal.** FR hip is the warmest joint."),
    [seg("All systems nominal.", true), seg(" FR hip is the warmest joint.")]);
  assert.deepEqual(splitBold("Battery at **66 %**, about **12 min** left."),
    [seg("Battery at "), seg("66 %", true), seg(", about "), seg("12 min", true), seg(" left.")]);
  assert.deepEqual(splitBold("__Caution:__ RL calf 142 °F"), [seg("Caution:", true), seg(" RL calf 142 °F")]);
});

test("plain text passes through untouched", () => {
  assert.deepEqual(splitBold("FR hip 133 °F · +2° in 10 min"), [seg("FR hip 133 °F · +2° in 10 min")]);
  assert.deepEqual(splitBold(""), []);
  assert.equal(plainText("FR_hip and RL_calf are within limits; 3 * 4 = 12"), "FR_hip and RL_calf are within limits; 3 * 4 = 12");
});

test("stray and other markers never reach the screen", () => {
  assert.equal(plainText("**No telemetry for 20 hours."), "No telemetry for 20 hours.");
  assert.equal(plainText("Telemetry is stale.** Check the link."), "Telemetry is stale. Check the link.");
  assert.equal(plainText("The *hottest* joint is `FR_hip`."), "The hottest joint is FR_hip.");
  assert.equal(plainText("## Status\nAll **clear**."), "Status\nAll clear.");
  assert.equal(plainText("**Bold with *nested* emphasis**"), "Bold with nested emphasis");
});
