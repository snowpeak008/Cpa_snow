import test from "node:test";
import assert from "node:assert/strict";
import { summarize, groups, trend, dateKey } from "./analytics.js";
const fixture = [
  {
    ts: new Date(2026, 0, 1, 12).getTime() / 1000,
    model: "a",
    key: "k",
    input: 100,
    cache: 60,
    output: 20,
    reasoning: 5,
    failed: false,
  },
  {
    ts: new Date(2026, 0, 1, 13).getTime() / 1000,
    model: "a",
    key: "k",
    input: 0,
    cache: 0,
    output: 0,
    reasoning: 0,
    failed: true,
  },
];
test("tokens are not double counted and zero-token failures are included", () => {
  const s = summarize(fixture);
  assert.equal(s.input + s.output, 120);
  assert.equal(s.n, 2);
  assert.equal(s.fail, 1);
});
test("grouping and trend use same total", () => {
  assert.equal(groups(fixture, "model")[0].n, 2);
  const b = trend(fixture, "day")[0];
  assert.equal(b.cache + b.net + b.output, 120);
});
test("local date does not use UTC slicing", () =>
  assert.equal(dateKey(new Date(2026, 0, 1)), "2026-01-01"));
