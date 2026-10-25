// 14. Modusberegning i frontend. Kjør: node --test tests/
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../app/static/modes.js");

const n = (h, m, room) => ({ h, m, room });

test("isFree per modus", () => {
  assert.equal(M.isFree(n(true, false, true), "h"), true);
  assert.equal(M.isFree(n(true, false, true), "m"), false);
  assert.equal(M.isFree(n(true, false, true), "b"), false);
  assert.equal(M.isFree(n(true, true, true), "b"), true);
  assert.equal(M.isFree(n(true, true, false), "h"), false, "gjesterom opptatt blokkerer alle moduser");
  assert.equal(M.isFree(undefined, "b"), false);
});

test("rangeStatus teller netter, avreisedag er eksklusiv", () => {
  const byDate = {
    "2026-12-12": n(true, true, true),
    "2026-12-13": n(true, false, true),
    "2026-12-14": n(true, true, true),
    "2026-12-15": n(false, false, true),
  };
  assert.deepEqual(M.rangeStatus(byDate, "2026-12-12", "2026-12-15", "h"), { nights: 3, allFree: true, blocked: [] });
  assert.deepEqual(M.rangeStatus(byDate, "2026-12-12", "2026-12-15", "b"), { nights: 3, allFree: false, blocked: ["2026-12-13"] });
  assert.equal(M.rangeStatus(byDate, "2026-12-12", "2026-12-12", "h").allFree, false);
});

test("ISO-ukenummer", () => {
  assert.equal(M.isoWeek("2026-12-28"), 53);
  assert.equal(M.isoWeek("2027-01-04"), 1);
  assert.equal(M.isoWeek("2026-10-26"), 44);
  assert.equal(M.isoWeek("2026-01-01"), 1);
});

test("addDays og daysBetween over sommertid", () => {
  assert.equal(M.addDays("2027-03-27", 2), "2027-03-29");
  assert.equal(M.daysBetween("2026-10-24", "2026-10-26"), 2);
});
