// Display-only Fahrenheit conversion (owner 2026-11-11). Run: node --test scripts/temp.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { cToF, showTemp, showTempText, TEMP_UNIT } from "../src/lib/temp.ts";

test("readings convert and round to whole degrees", () => {
  assert.equal(TEMP_UNIT, "°F");
  assert.equal(cToF(0), 32);
  assert.equal(showTemp(55), "131");      // joint caution limit
  assert.equal(showTemp(70), "158");      // joint warning limit
  assert.equal(showTemp(53.4), "128");
  assert.equal(showTemp(null), "--");
  assert.equal(showTemp(undefined), "--");
  assert.equal(showTemp(Number.NaN), "--");
});

test("server-written findings are rewritten for display", () => {
  // deploy/azure/adx/setup.kql Overwatch_Findings and cloud/query_api/backends/aws.py write these shapes
  assert.equal(showTempText("FR hip 56 °C · +1° in 10 min · 14 min in caution"), "FR hip 133 °F · +2° in 10 min · 14 min in caution");
  assert.equal(showTempText("RL calf 61 °C · −3° in 5 min"), "RL calf 142 °F · −5° in 5 min");
  assert.equal(showTempText("Thor 86 °C"), "Thor 187 °F");
  assert.equal(showTempText("RR hip 58 °C · steady"), "RR hip 136 °F · steady");
});

test("the synthetic feed's wording, with non-breaking spaces and rates", () => {
  assert.equal(showTempText("FL thigh 72 °C · over limit"), "FL thigh 162 °F · over limit");
  assert.equal(showTempText("RL calf 61 °C · rising 3.0 °C/min"), "RL calf 142 °F · rising 5.4 °F/min");
  assert.equal(showTempText("FR hip 56 °C +0.5 °C/min"), "FR hip 133 °F +0.9 °F/min");
});

test("agent prose: ranges, limits and text with no temperature", () => {
  assert.equal(showTempText("Caution starts at 55 °C and warning at 70 °C."), "Caution starts at 131 °F and warning at 158 °F.");
  assert.equal(showTempText("76 °C on the rear hips against 33–42 °C elsewhere"), "169 °F on the rear hips against 91–108 °F elsewhere");
  assert.equal(showTempText("Ambient range 5-35 °C"), "Ambient range 41-95 °F");
  assert.equal(showTempText("Lidar rated −10 to 60 °C"), "Lidar rated 14 to 140 °F");
  assert.equal(showTempText("tilt 34° · battery 66 % · 12 min left"), "tilt 34° · battery 66 % · 12 min left");
  assert.equal(showTempText("Already 131 °F."), "Already 131 °F.");
  assert.equal(showTempText(""), "");
});

test("below zero, spelled-out units and stray symbols", () => {
  assert.equal(showTempText("Storage −20 to −5 °C"), "Storage −4 to 23 °F");
  assert.equal(showTempText("Cold soak at −30 °C"), "Cold soak at −22 °F");
  assert.equal(showTempText("Warning at 70 degrees Celsius, caution at 55 degrees C."), "Warning at 158 degrees Fahrenheit, caution at 131 degrees F.");
  assert.equal(showTempText("Readings are in °C"), "Readings are in °C");   // no number to convert
  assert.equal(showTempText("Go2-35 °C"), "Go2-95 °F");                      // a model name is not a range start
});
