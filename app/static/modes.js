/* Ren logikk for moduser og perioder. Brukes i nettleseren (window.BesokModes) og i Node-testen. */
(function (root) {
  "use strict";

  var MODES = { h: "Håvard", m: "Marianne", b: "Begge" };

  function isFree(night, mode) {
    if (!night || !night.room) return false;
    if (mode === "h") return !!night.h;
    if (mode === "m") return !!night.m;
    return !!(night.h && night.m);
  }

  function addDays(iso, n) {
    var d = new Date(iso + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }

  function daysBetween(a, b) {
    return Math.round((Date.parse(b + "T12:00:00Z") - Date.parse(a + "T12:00:00Z")) / 86400000);
  }

  /* Periode fra ankomst (inkl.) til avreise (ekskl.). byDate: { "YYYY-MM-DD": night } */
  function rangeStatus(byDate, arrival, departure, mode) {
    var n = daysBetween(arrival, departure);
    if (n < 1) return { nights: 0, allFree: false, blocked: [] };
    var blocked = [];
    for (var i = 0; i < n; i++) {
      var iso = addDays(arrival, i);
      if (!isFree(byDate[iso], mode)) blocked.push(iso);
    }
    return { nights: n, allFree: blocked.length === 0, blocked: blocked };
  }

  /* ISO-8601-ukenummer */
  function isoWeek(iso) {
    var d = new Date(iso + "T12:00:00Z");
    var day = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - day);
    var yearStart = Date.UTC(d.getUTCFullYear(), 0, 1);
    var dayOfYear = Math.floor((d - yearStart) / 86400000); // 0-basert, uten klokkeslett
    return Math.floor(dayOfYear / 7) + 1;
  }

  var api = { MODES: MODES, isFree: isFree, rangeStatus: rangeStatus, isoWeek: isoWeek, addDays: addDays, daysBetween: daysBetween };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.BesokModes = api;
})(this);
