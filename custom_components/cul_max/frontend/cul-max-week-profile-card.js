/*
 * CUL MAX! week profile card
 *
 * - 24 h timeline per day, coloured by temperature, with a "now" marker
 * - status: mode, target vs. schedule, window open, upload progress, last command
 * - next switching point
 * - inline day editor (times / temperatures, add / remove points, copy to days)
 *   that uploads through cul_max.set_week_profile_days
 */

const DAYS = [
  ["monday", "Mo", "Montag"],
  ["tuesday", "Di", "Dienstag"],
  ["wednesday", "Mi", "Mittwoch"],
  ["thursday", "Do", "Donnerstag"],
  ["friday", "Fr", "Freitag"],
  ["saturday", "Sa", "Samstag"],
  ["sunday", "So", "Sonntag"],
];
const JS_DAY_TO_KEY = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const MAX_POINTS = 13;
const TEMP_MIN = 4.5;
const TEMP_MAX = 30.5;
const MODE_LABELS = {
  auto: "Automatik",
  manual: "Manuell",
  vacation: "Urlaub",
  boost: "Boost",
};

// UI language: German for "de*", English for everything else. DAYS and
// MODE_LABELS are switched in place so all code using them follows.
const DAY_NAMES = {
  de: { monday: ["Mo", "Montag"], tuesday: ["Di", "Dienstag"], wednesday: ["Mi", "Mittwoch"], thursday: ["Do", "Donnerstag"],
    friday: ["Fr", "Freitag"], saturday: ["Sa", "Samstag"], sunday: ["So", "Sonntag"] },
  en: { monday: ["Mon", "Monday"], tuesday: ["Tue", "Tuesday"], wednesday: ["Wed", "Wednesday"], thursday: ["Thu", "Thursday"],
    friday: ["Fri", "Friday"], saturday: ["Sat", "Saturday"], sunday: ["Sun", "Sunday"] },
};
const MODE_NAMES = {
  de: { auto: "Automatik", manual: "Manuell", vacation: "Urlaub", boost: "Boost" },
  en: { auto: "Auto", manual: "Manual", vacation: "Vacation", boost: "Boost" },
};
let wLang = "de";
let wLocale = "de-DE";
const wSetLang = (hass) => {
  const language = String(hass?.locale?.language || hass?.language || "en");
  const lang = language.toLowerCase().startsWith("de") ? "de" : "en";
  wLocale = lang === "de" ? "de-DE" : language.includes("-") ? language : "en-GB";
  if (lang === wLang) return;
  wLang = lang;
  DAYS.forEach((day) => {
    [day[1], day[2]] = DAY_NAMES[lang][day[0]];
  });
  Object.assign(MODE_LABELS, MODE_NAMES[lang]);
};
const W_TEXT = {
  de: {
    off: "Aus",
    needSegment: "Mindestens ein Abschnitt ist nötig.",
    maxSegments: (n) => `Höchstens ${n} Abschnitte pro Tag.`,
    badTemp: (t) => `Temperatur ${t} ist ungültig (4,5–30,5 °C in 0,5er-Schritten).`,
    fillTimes: "Bitte alle Uhrzeiten ausfüllen.",
    fiveMinutes: (t) => `${t}: nur 5-Minuten-Schritte möglich.`,
    ascending: (t) => `${t}: Uhrzeiten müssen aufsteigend sein.`,
    before24: "Die letzte Schaltzeit muss vor 24:00 liegen.",
    title: "Wochenprofil",
    tomorrow: "morgen",
    windowOpen: (partners) => `Fenster offen${partners ? ` (${partners})` : ""} – Absenkung aktiv`,
    deviates: (thermostat, plan) => `Weicht vom Plan ab: Thermostat ${thermostat}, Plan ${plan}`,
    pairedElsewhere: (central) => `Noch an einer anderen Zentrale angemeldet (${central}) – Gerät zurücksetzen und neu anlernen`,
    vacationUntil: (d, m, time) => ` bis ${d}.${m}. ${time}`,
    vacation: (until, temp) => `Urlaub${until} – ${temp}, danach wieder Wochenprogramm`,
    summer: (open) => `Sommermodus – ${open ? "Ventil ganz offen" : "Heizung aus"}, Wochenprogramm pausiert bis zum Ende des Sommermodus`,
    programInactive: (mode, target) => `Wochenprogramm nicht aktiv – Modus ${mode}${target}`,
    uploading: (n) => `Übertragung zum Thermostat: noch ${n} Paket(e)`,
    sendingCmd: (cmd) => `Sende: ${cmd} …`,
    notConfirmed: (cmd) => `Nicht bestätigt: ${cmd}`,
    fromWallThermostat: "Profil vom verknüpften Wandthermostat – dort bearbeiten",
    entityMissing: (ids) => `Entität nicht gefunden: ${ids}`,
    incompatible: (ids) => `<b>Inkompatible Entität</b><br>Diese Karte funktioniert nur mit <code>cul_max</code>-Climate-Entitäten.<br>Gewählt: <code>${ids}</code>`,
    details: "Details",
    programUnknown: "Wochenprogramm unbekannt",
    programUnknownFor: (days) => `Programm unbekannt für ${days}`,
    cannotReport: "MAX!-Geräte können ihr Programm nicht melden (z. B. wenn es mit dem Cube eingestellt wurde).",
    tapToSet: "Tag antippen, um ihn hier festzulegen; mit „Auch übernehmen für“ gleich für mehrere Tage.",
    profilesDiffer: (days) => `Profile unterscheiden sich: ${days} – ein bearbeiteter Tag wird für alle Thermostate übernommen`,
    profilesDifferShort: "Profile unterscheiden sich",
    unknown: "unbekannt",
    editDay: (day) => `${day} bearbeiten`,
    nextSwitch: (next) => `Nächster Wechsel: ${next}`,
    tapToEdit: "Tag antippen zum Bearbeiten",
    untilThen: (when, temp) => `bis ${when}, danach ${temp} laut Plan`,
    untilNext: "bis zum nächsten Schaltpunkt",
    sendingSoon: "wird gleich gesendet …",
    temporary: (until) => `vorübergehend – ${until}`,
    byPlan: (until) => `laut Plan ${until}`,
    thermostatsDiffer: "Thermostate unterschiedlich",
    colder: "0,5 °C kälter bis zum nächsten Schaltpunkt",
    warmer: "0,5 °C wärmer bis zum nächsten Schaltpunkt",
    backToPlan: "Zurück zum Plan",
    confirmedAt: (at) => `bestätigt ${at}`,
    sending: "wird übertragen …",
    unconfirmed: "vom Thermostat nicht bestätigt, neuer Versuch folgt",
    sensorStale: "Sensor liefert keine aktuellen Werte – Thermostat regelt selbst",
    sensorMissing: "Sensor nicht verfügbar – Thermostat regelt selbst",
    regulateOn: "Regelung nach",
    ownSensor: "Fühler am Thermostat",
    sameRoom: "gleicher Raum",
    ownSensorDefault: "Fühler am Thermostat (Standard)",
    sensorNote: (multi) => `Das Thermostat regelt dann nach diesem Sensor statt nach seinem Fühler am Heizkörper (virtuelles Wandthermostat). Das Wochenprogramm bleibt auf dem Thermostat.${multi ? " Gilt für alle Thermostate dieser Karte." : ""}`,
    cancel: "Abbrechen",
    settingUp: "Wird eingerichtet …",
    apply: "Übernehmen",
    change: "ändern",
    offOption: "Aus (4,5)",
    untilLabel: "bis (hh:mm)",
    removeSegment: "Abschnitt entfernen",
    editTitle: (day) => `${day} bearbeiten`,
    forTargets: (names) => `für ${names}`,
    addPoint: "Schaltpunkt",
    alsoApply: "Auch übernehmen für:",
    workdays: "Mo–Fr",
    weekend: "Sa–So",
    all: "Alle",
    none: "Keine",
    uploadingProgress: (p) => `Wird übertragen${p ? ` (${p})` : ""} …`,
    upload: "Übertragen",
    radioNote: "Jeder Tag braucht 1–2 Funkpakete. Thermostate übernehmen das Profil, sobald sie es empfangen haben; der Fortschritt erscheint oben.",
    fromOtherRoom: "Aus anderem Raum übernehmen …",
    noOtherThermostat: "Kein anderes MAX!-Thermostat mit bekanntem Wochenprogramm.",
    close: "Schließen",
    noArea: "Ohne Bereich",
    weekNote: (targets, unknown) => `Überträgt die ganze Woche${targets > 1 ? ` an ${targets} Thermostate` : ""} – bis zu 14 Funkpakete pro Thermostat, das dauert einige Minuten.${unknown ? ` Unbekannt und übersprungen: ${unknown}.` : ""}`,
    onlyDay: (day) => `nur ${day}`,
    wholeWeek: "ganze Woche",
    sendWholeWeek: "Ganze Woche übertragen",
    intoEditor: "In den Editor übernehmen",
    dayUnknownThere: "Für diesen Tag ist das Programm dort unbekannt.",
    pick: "Bitte wählen",
    moreThermostats: "Weitere Thermostate im selben Raum (gemeinsame Karte)",
    titleLabel: "Titel",
    showCurrent: "Ist-Temperatur anzeigen",
    allowEdit: "Bearbeiten in der Karte erlauben",
  },
  en: {
    off: "Off",
    needSegment: "At least one segment is needed.",
    maxSegments: (n) => `At most ${n} segments per day.`,
    badTemp: (t) => `Temperature ${t} is invalid (4.5–30.5 °C in steps of 0.5).`,
    fillTimes: "Please fill in all times.",
    fiveMinutes: (t) => `${t}: only steps of 5 minutes are possible.`,
    ascending: (t) => `${t}: times must be ascending.`,
    before24: "The last switching time must be before 24:00.",
    title: "Week program",
    tomorrow: "tomorrow",
    windowOpen: (partners) => `Window open${partners ? ` (${partners})` : ""} – lowered`,
    deviates: (thermostat, plan) => `Differs from the schedule: thermostat ${thermostat}, schedule ${plan}`,
    pairedElsewhere: (central) => `Still paired with another central (${central}) – reset the device and pair it again`,
    vacationUntil: (d, m, time) => ` until ${d}/${m} ${time}`,
    vacation: (until, temp) => `Vacation${until} – ${temp}, then back to the week program`,
    summer: (open) => `Summer mode – ${open ? "valve fully open" : "heating off"}, week program paused until summer mode ends`,
    programInactive: (mode, target) => `Week program not active – mode ${mode}${target}`,
    uploading: (n) => `Sending to the thermostat: ${n} packet(s) left`,
    sendingCmd: (cmd) => `Sending: ${cmd} …`,
    notConfirmed: (cmd) => `Not confirmed: ${cmd}`,
    fromWallThermostat: "Profile of the linked wall thermostat – edit it there",
    entityMissing: (ids) => `Entity not found: ${ids}`,
    incompatible: (ids) => `<b>Incompatible entity</b><br>This card only works with <code>cul_max</code> climate entities.<br>Selected: <code>${ids}</code>`,
    details: "Details",
    programUnknown: "Week program unknown",
    programUnknownFor: (days) => `Program unknown for ${days}`,
    cannotReport: "MAX! devices cannot report their program (e.g. when it was set with the Cube).",
    tapToSet: "Tap a day to set it here; use \"Also apply to\" for several days at once.",
    profilesDiffer: (days) => `Profiles differ: ${days} – an edited day is applied to all thermostats`,
    profilesDifferShort: "Profiles differ",
    unknown: "unknown",
    editDay: (day) => `Edit ${day}`,
    nextSwitch: (next) => `Next change: ${next}`,
    tapToEdit: "Tap a day to edit",
    untilThen: (when, temp) => `until ${when}, then ${temp} per schedule`,
    untilNext: "until the next switching point",
    sendingSoon: "sending shortly …",
    temporary: (until) => `temporary – ${until}`,
    byPlan: (until) => `per schedule ${until}`,
    thermostatsDiffer: "thermostats differ",
    colder: "0.5 °C colder until the next switching point",
    warmer: "0.5 °C warmer until the next switching point",
    backToPlan: "Back to schedule",
    confirmedAt: (at) => `confirmed ${at}`,
    sending: "sending …",
    unconfirmed: "not confirmed by the thermostat, retrying",
    sensorStale: "sensor reports no current values – thermostat regulates itself",
    sensorMissing: "sensor unavailable – thermostat regulates itself",
    regulateOn: "Regulating on",
    ownSensor: "sensor at the thermostat",
    sameRoom: "same room",
    ownSensorDefault: "Sensor at the thermostat (default)",
    sensorNote: (multi) => `The thermostat then regulates on this sensor instead of its sensor at the radiator (virtual wall thermostat). The week program stays on the thermostat.${multi ? " Applies to all thermostats of this card." : ""}`,
    cancel: "Cancel",
    settingUp: "Setting up …",
    apply: "Apply",
    change: "change",
    offOption: "Off (4.5)",
    untilLabel: "until (hh:mm)",
    removeSegment: "Remove segment",
    editTitle: (day) => `Edit ${day}`,
    forTargets: (names) => `for ${names}`,
    addPoint: "Switching point",
    alsoApply: "Also apply to:",
    workdays: "Mon–Fri",
    weekend: "Sat–Sun",
    all: "All",
    none: "None",
    uploadingProgress: (p) => `Sending${p ? ` (${p})` : ""} …`,
    upload: "Send",
    radioNote: "Each day needs 1–2 radio packets. Thermostats take over the profile once they have received it; progress shows above.",
    fromOtherRoom: "Copy from another room …",
    noOtherThermostat: "No other MAX! thermostat with a known week program.",
    close: "Close",
    noArea: "No area",
    weekNote: (targets, unknown) => `Sends the whole week${targets > 1 ? ` to ${targets} thermostats` : ""} – up to 14 radio packets per thermostat, this takes a few minutes.${unknown ? ` Unknown and skipped: ${unknown}.` : ""}`,
    onlyDay: (day) => `only ${day}`,
    wholeWeek: "whole week",
    sendWholeWeek: "Send whole week",
    intoEditor: "Copy into the editor",
    dayUnknownThere: "The program of this day is unknown there.",
    pick: "Please choose",
    moreThermostats: "More thermostats in the same room (shared card)",
    titleLabel: "Title",
    showCurrent: "Show current temperature",
    allowEdit: "Allow editing in the card",
  },
};
const WT = () => W_TEXT[wLang];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

const toMinutes = (hhmm) => {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm || "").trim());
  if (!match) return NaN;
  return Number(match[1]) * 60 + Number(match[2]);
};

const toHHMM = (minutes) => {
  if (!Number.isFinite(minutes)) return "--:--";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
};

const fmtTemp = (temp) => {
  const value = Number(temp);
  if (!Number.isFinite(value)) return "–";
  if (value <= TEMP_MIN) return WT().off;
  return `${value.toLocaleString(wLocale, { minimumFractionDigits: 0, maximumFractionDigits: 1 })} °C`;
};

/** Colour bands: off grey, frost/eco blues, comfort amber → orange → red. */
const TEMP_BANDS = [
  [TEMP_MIN, "#8a8f98"], // off
  [12, "#3d6fb6"], // frost protection / absent
  [17, "#3f8fc4"], // cool
  [19.5, "#2f9e9e"], // eco
  [21, "#d08a1e"], // comfort
  [23, "#e0692a"], // warm
  [99, "#cf4a3c"], // hot
];
const tempColor = (temp) => {
  const value = Number(temp);
  if (!Number.isFinite(value)) return TEMP_BANDS[0][1];
  return TEMP_BANDS.find(([limit]) => value <= limit)[1];
};

/** "18,06:05,22,15:30,18" → [{from, until, temp}] in minutes. */
const parseDay = (raw) => {
  if (!raw || typeof raw !== "string") return [];
  const tokens = raw.split(",").map((t) => t.trim()).filter(Boolean);
  if (!tokens.length) return [];
  const segments = [];
  let from = 0;
  let temp = Number(tokens[0]);
  for (let i = 1; i < tokens.length; i += 2) {
    let until = toMinutes(tokens[i]);
    if (!Number.isFinite(until)) break;
    if (until === 0) until = 24 * 60;
    if (until > from) segments.push({ from, until, temp });
    from = until;
    if (until >= 24 * 60) break;
    if (tokens[i + 1] !== undefined) temp = Number(tokens[i + 1]);
  }
  if (from < 24 * 60) segments.push({ from, until: 24 * 60, temp });
  // merge neighbours with identical temperature
  return segments.reduce((acc, seg) => {
    const last = acc[acc.length - 1];
    if (last && last.temp === seg.temp && last.until === seg.from) {
      last.until = seg.until;
    } else {
      acc.push({ ...seg });
    }
    return acc;
  }, []);
};

/** [{from, until, temp}] → "18,06:05,22,15:30,18" */
const serializeDay = (segments) => {
  const parts = [];
  segments.forEach((seg, idx) => {
    parts.push(String(seg.temp));
    if (idx < segments.length - 1) parts.push(toHHMM(seg.until));
  });
  return parts.join(",");
};

const validateDay = (segments) => {
  if (!segments.length) return WT().needSegment;
  if (segments.length > MAX_POINTS) return WT().maxSegments(MAX_POINTS);
  let previous = 0;
  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    if (!(seg.temp >= TEMP_MIN && seg.temp <= TEMP_MAX) || (seg.temp * 2) % 1 !== 0) {
      return WT().badTemp(seg.temp);
    }
    if (i < segments.length - 1) {
      if (!Number.isFinite(seg.until)) return WT().fillTimes;
      if (seg.until % 5 !== 0) return WT().fiveMinutes(toHHMM(seg.until));
      if (seg.until <= previous) return WT().ascending(toHHMM(seg.until));
      if (seg.until >= 24 * 60) return WT().before24;
      previous = seg.until;
    }
  }
  return null;
};

class CulMaxWeekProfileCard extends HTMLElement {
  static _isCulMaxClimate(entityId, state) {
    const attrs = state?.attributes || {};
    return (
      entityId?.startsWith("climate.") &&
      attrs.address !== undefined &&
      attrs.pairing_state !== undefined
    );
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find((entityId) =>
        CulMaxWeekProfileCard._isCulMaxClimate(entityId, hass.states[entityId])
      ) || "";
    return { entity, show_current_temp: true, editable: true };
  }

  static getConfigElement() {
    return document.createElement("cul-max-week-profile-card-editor");
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._editing = null; // { day, segments, copyTo:Set, busy, error }
    this._sensorEdit = null; // { value, busy, error }
    this._lastStateObj = null;
  }

  setConfig(config) {
    const hasList = Array.isArray(config?.entities) && config.entities.length > 0;
    if (!config || (!config.entity && !hasList)) {
      throw new Error("Entity required");
    }
    this._config = {
      show_current_temp: true,
      editable: true,
      ...config,
    };
    this._lastStates = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const langBefore = wLang;
    wSetLang(hass);
    const states = this._entityIds().map((id) => hass?.states?.[id]);
    // Only re-render when one of our entities changed; keeps an open editor intact.
    const changed =
      langBefore !== wLang ||
      !this._lastStates ||
      states.length !== this._lastStates.length ||
      states.some((st, idx) => st !== this._lastStates[idx]);
    if (changed) {
      this._lastStates = states;
      this._refresh();
    }
  }

  /** One or more thermostats (e.g. several radiators in a room). */
  _entityIds() {
    const cfg = this._config || {};
    const list = Array.isArray(cfg.entities) && cfg.entities.length ? cfg.entities : [cfg.entity];
    return [
      ...new Set(
        list
          .map((item) => (typeof item === "string" ? item : item?.entity))
          .filter(Boolean)
      ),
    ];
  }

  /** Short names: strip the words all thermostat names share. */
  _shortNames(stateObjs) {
    const names = stateObjs.map((st, idx) => st?.attributes?.friendly_name || this._entityIds()[idx]);
    if (names.length < 2) return names;
    const words = names.map((n) => n.split(/\s+/));
    let common = 0;
    while (words.every((w) => w.length > common + 1 && w[common] === words[0][common])) common += 1;
    return words.map((w, idx) => w.slice(common).join(" ") || names[idx]);
  }

  connectedCallback() {
    // keep the "now" marker and next switch point current
    this._timer = window.setInterval(() => this._refresh(), 60 * 1000);
  }

  disconnectedCallback() {
    window.clearInterval(this._timer);
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _stateObj() {
    return this._hass?.states?.[this._entityIds()[0]];
  }

  /** Card title; the German default "Wochenprofil" (alone or as in
   *  "Büro Wochenprofil") is translated, everything else stays as configured. */
  _title() {
    const title = String(this._config.title || "").trim();
    const de = W_TEXT.de.title;
    if (!title || title === de) return WT().title;
    if (title.endsWith(` ${de}`)) return `${title.slice(0, -de.length)}${WT().title}`;
    return title;
  }

  _daySegments(attrs, key) {
    return parseDay(attrs[`week_profile_${key}`]);
  }

  _nextSwitch(attrs, now) {
    const todayIndex = DAYS.findIndex(([key]) => key === JS_DAY_TO_KEY[now.getDay()]);
    const minutes = now.getHours() * 60 + now.getMinutes();
    for (let offset = 0; offset < 7; offset += 1) {
      const [key, , longLabel] = DAYS[(todayIndex + offset) % 7];
      const segments = this._daySegments(attrs, key);
      if (!segments.length) return null; // unknown day: no reliable prediction
      for (const seg of segments) {
        if (seg.from === 0) continue;
        if (offset === 0 && seg.from <= minutes) continue;
        const when = offset === 0 ? "" : offset === 1 ? `${WT().tomorrow} ` : `${longLabel} `;
        return `${when}${toHHMM(seg.from)} → ${fmtTemp(seg.temp)}`;
      }
    }
    return null;
  }

  _statusItems(stateObj, prefix = "") {
    const attrs = stateObj.attributes || {};
    const items = [];
    const who = prefix ? `${esc(prefix)}: ` : "";
    const mode = attrs.mode_detail;
    if (attrs.window_open_active) {
      const partners = (attrs.open_window_partner_names || []).join(", ");
      items.push({
        level: "warn",
        icon: "mdi:window-open-variant",
        text: `${who}${WT().windowOpen(partners ? esc(partners) : "")}`,
      });
    } else if (
      mode === "auto" &&
      attrs.week_profile_validation === "mismatch" &&
      attrs.expected_week_profile_temperature != null &&
      attrs.temperature != null
    ) {
      items.push({
        level: "warn",
        icon: "mdi:alert-outline",
        text: `${who}${WT().deviates(fmtTemp(attrs.temperature), fmtTemp(attrs.expected_week_profile_temperature))}`,
      });
    }
    if (attrs.pairing_state === "paired_elsewhere") {
      items.push({
        level: "error",
        icon: "mdi:link-off",
        text: `${who}${WT().pairedElsewhere(esc(attrs.paired_elsewhere_central || "?"))}`,
      });
    }
    const scheduleOff = attrs.week_profile_source !== undefined || attrs.week_profile_monday !== undefined;
    if (mode === "vacation") {
      const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})/.exec(attrs.until || "");
      const until = m ? WT().vacationUntil(m[3], m[2], m[4]) : "";
      items.push({
        level: "info",
        icon: "mdi:airplane",
        text: `${who}${WT().vacation(until, fmtTemp(attrs.temperature))}`,
      });
    } else if (attrs.summer_mode) {
      items.push({
        level: "info",
        icon: "mdi:white-balance-sunny",
        text: `${who}${WT().summer(attrs.summer_mode === "open")}`,
      });
    } else if (scheduleOff && mode && mode !== "auto") {
      const label = stateObj.state === "off" ? WT().off : MODE_LABELS[mode] || mode;
      const target = attrs.temperature != null && stateObj.state !== "off" ? ` ${fmtTemp(attrs.temperature)}` : "";
      items.push({
        level: "info",
        icon: "mdi:pause-circle-outline",
        text: `${who}${WT().programInactive(esc(label), target)}`,
      });
    }
    if (attrs.pending_queue_type === "climate" && attrs.pending_queue_length > 0) {
      const error = attrs.pending_queue_last_error ? ` – ${esc(attrs.pending_queue_last_error)}` : "";
      items.push({
        level: attrs.pending_queue_last_error ? "warn" : "info",
        icon: "mdi:upload-network-outline",
        text: `${who}${WT().uploading(attrs.pending_queue_length)}${
          attrs.pending_queue_active ? " …" : ""
        }${error}`,
      });
    }
    if (attrs.command_status === "sending") {
      items.push({ level: "info", icon: "mdi:radio-tower", text: `${who}${WT().sendingCmd(esc(attrs.command_requested))}` });
    } else if (attrs.command_status === "failed") {
      items.push({
        level: "error",
        icon: "mdi:alert-circle-outline",
        text: `${who}${WT().notConfirmed(esc(attrs.command_requested))}${
          attrs.command_error ? ` (${esc(attrs.command_error)})` : ""
        }`,
      });
    }
    if (attrs.week_profile_source === "linked_partner") {
      items.push({
        level: "info",
        icon: "mdi:link-variant",
        text: `${who}${WT().fromWallThermostat}`,
      });
    }
    return items;
  }

  /** Re-render after an external change (state update, timer). */
  _refresh() {
    // keep values typed into the editor but not yet committed
    if (this._editing && !this._editing.busy && this.shadowRoot.querySelector(".editor")) {
      this._readEditorInputs();
    }
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    const root = this.shadowRoot;
    const ids = this._entityIds();
    const stateObjs = ids.map((id) => this._hass.states[id]);
    const missing = ids.filter((id, idx) => !stateObjs[idx]);
    if (missing.length) {
      root.innerHTML = `<ha-card><div class="msg">${WT().entityMissing(esc(missing.join(", ")))}</div></ha-card>${this._styles()}`;
      return;
    }
    const incompatible = ids.filter((id, idx) => !CulMaxWeekProfileCard._isCulMaxClimate(id, stateObjs[idx]));
    if (incompatible.length) {
      root.innerHTML = `
        <ha-card><div class="msg">${WT().incompatible(esc(incompatible.join(", ")))}</div></ha-card>${this._styles()}`;
      return;
    }

    const stateObj = stateObjs[0];
    const attrs = stateObj.attributes || {};
    const multi = stateObjs.length > 1;
    const shortNames = this._shortNames(stateObjs);
    const now = new Date();
    const nowMinutes = now.getHours() * 60 + now.getMinutes();
    const todayKey = JS_DAY_TO_KEY[now.getDay()];
    const allAttrs = stateObjs.map((st) => st.attributes || {});
    const hasProfile = allAttrs.every((a) => DAYS.some(([key]) => a[`week_profile_${key}`]));
    const fromPartner = allAttrs.some((a) => a.week_profile_source === "linked_partner");
    // Unknown days (program written elsewhere, e.g. by the old Cube – MAX!
    // devices cannot report it) can be set here as well.
    const editable = this._config.editable !== false && !fromPartner;
    const unknownDays = DAYS.filter(([key]) => allAttrs.some((a) => !a[`week_profile_${key}`]));
    this._editableTargets = ids;

    const chipsFor = (st) => {
      const a = st.attributes || {};
      const chips = [];
      const modeLabel = st.state === "off" ? WT().off : MODE_LABELS[a.mode_detail] || st.state;
      chips.push(`<span class="chip mode">${esc(modeLabel)}</span>`);
      if (a.temperature != null) {
        chips.push(`<span class="chip"><ha-icon icon="mdi:target"></ha-icon>${fmtTemp(a.temperature)}</span>`);
      }
      if (this._config.show_current_temp && a.current_temperature != null) {
        chips.push(
          `<span class="chip"><ha-icon icon="mdi:thermometer"></ha-icon>${fmtTemp(a.current_temperature)}</span>`
        );
      }
      if (a.valve_position != null && a.valve_position > 0) {
        chips.push(`<span class="chip"><ha-icon icon="mdi:valve"></ha-icon>${a.valve_position}\u202f%</span>`);
      }
      return chips.join("");
    };
    const chipsHtml = multi
      ? stateObjs
          .map(
            (st, idx) =>
              `<div class="chips pick" role="button" tabindex="0" data-entity="${esc(st.entity_id)}"
                    title="${esc(st.attributes.friendly_name || st.entity_id)} – ${WT().details}"><span class="who">${esc(
                shortNames[idx]
              )}</span>${chipsFor(st)}</div>`
          )
          .join("")
      : `<div class="chips">${chipsFor(stateObj)}</div>`;

    const quickHtml = this._quickChangeHtml(stateObjs);

    // per day: normalised profile of every thermostat
    const dayProfiles = Object.fromEntries(
      DAYS.map(([key]) => [key, allAttrs.map((a) => this._daySegments(a, key))])
    );
    const differingDays = DAYS.filter(([key]) => {
      const strings = dayProfiles[key].map((segs) => serializeDay(segs));
      return strings.some((str) => str !== strings[0]);
    });

    const next = hasProfile ? this._nextSwitch(attrs, now) : null;
    const statusItems = stateObjs.flatMap((st, idx) => this._statusItems(st, multi ? shortNames[idx] : ""));
    if (unknownDays.length) {
      const which =
        unknownDays.length === DAYS.length
          ? WT().programUnknown
          : WT().programUnknownFor(unknownDays.map(([, short]) => short).join(", "));
      statusItems.push({
        level: "info",
        icon: "mdi:help-circle-outline",
        text: `${which} – ${WT().cannotReport} ${editable ? esc(WT().tapToSet) : ""}`,
      });
    }
    if (multi && differingDays.length) {
      statusItems.push({
        level: "info",
        icon: "mdi:call-split",
        text: WT().profilesDiffer(differingDays.map(([, short]) => short).join(", ")),
      });
    }
    const status = statusItems
      .map(
        (item) =>
          `<div class="status ${item.level}"><ha-icon icon="${item.icon}"></ha-icon><span>${item.text}</span></div>`
      )
      .join("");

    const barHtml = (segments, isToday, long, label = "") => {
      const bar = segments.length
        ? segments
            .map((seg) => {
              const left = (seg.from / 1440) * 100;
              const width = ((seg.until - seg.from) / 1440) * 100;
              const active = isToday && nowMinutes >= seg.from && nowMinutes < seg.until;
              return `<div class="seg${active ? " active" : ""}"
                  style="left:${left}%;width:${width}%;background:${tempColor(seg.temp)}"
                  title="${esc(label ? `${label}: ` : "")}${long} ${toHHMM(seg.from)}–${toHHMM(seg.until)}: ${fmtTemp(seg.temp)}">
                  ${width >= 9 ? `<span>${fmtTemp(seg.temp)}</span>` : ""}
                </div>`;
            })
            .join("")
        : `<div class="empty">${WT().unknown}</div>`;
      const marker = isToday ? `<div class="now" style="left:${(nowMinutes / 1440) * 100}%"></div>` : "";
      // switching times below the bar; labels that would overlap the previous
      // one on the same line move to a second line
      const lastOnLine = [-Infinity, -Infinity];
      let lines = 1;
      const times = segments
        .slice(1)
        .map((seg) => {
          const pos = (seg.from / 1440) * 100;
          const line = pos - lastOnLine[0] >= 8 ? 0 : pos - lastOnLine[1] >= 8 ? 1 : 0;
          lastOnLine[line] = pos;
          lines = Math.max(lines, line + 1);
          return `<span class="l${line}" style="left:${pos}%">${toHHMM(seg.from)}</span>`;
        })
        .join("");
      return `${label ? `<div class="who-label">${esc(label)}</div>` : ""}
        <div class="bar">${bar}${marker}</div>
        <div class="times${lines > 1 ? " two" : ""}">${times}</div>`;
    };

    const rows = DAYS.map(([key, short, long]) => {
      const isToday = key === todayKey;
      const differs = differingDays.some(([k]) => k === key);
      const track = differs
        ? dayProfiles[key].map((segs, idx) => barHtml(segs, isToday, long, shortNames[idx])).join("")
        : barHtml(dayProfiles[key][0], isToday, long);
      const editingThis = this._editing?.day === key;
      return `
        <div class="day-row${isToday ? " today" : ""}${editable ? " editable" : ""}${editingThis ? " editing" : ""}"
             data-day="${key}" ${editable ? `role="button" tabindex="0" aria-label="${esc(WT().editDay(long))}"` : ""}>
          <div class="label">${short}${differs ? `<span class="diff" title="${WT().profilesDifferShort}">≠</span>` : ""}</div>
          <div class="track">${track}</div>
        </div>
        ${editingThis ? this._editorHtml(key, long, multi ? shortNames : null) : ""}`;
    }).join("");

    root.innerHTML = `
      <ha-card>
        <div class="wrapper">
          <div class="header">
            <div class="titles">
              <div class="title">${esc(this._title())}</div>
              <div class="subtitle">${esc(
                multi ? stateObjs.map((st) => st.attributes.friendly_name).join(" · ") : attrs.friendly_name || ""
              )}</div>
            </div>
            <div class="more-wrap">
              <ha-icon-button class="more" label="${WT().details}"><ha-icon icon="mdi:dots-vertical"></ha-icon></ha-icon-button>
              ${
                multi
                  ? `<div class="more-menu" hidden>${stateObjs
                      .map(
                        (st) =>
                          `<button class="more-item" data-entity="${esc(st.entity_id)}">${esc(
                            st.attributes.friendly_name || st.entity_id
                          )}</button>`
                      )
                      .join("")}</div>`
                  : ""
              }
            </div>
          </div>
          ${chipsHtml}
          ${quickHtml || (next ? `<div class="next"><ha-icon icon="mdi:clock-outline"></ha-icon>${WT().nextSwitch(next)}</div>` : "")}
          ${status}
          ${this._sensorRowHtml(stateObjs, shortNames)}
          <div class="axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
          <div class="days">${rows}</div>
          ${editable && !this._editing ? `<div class="hint">${WT().tapToEdit}</div>` : ""}
        </div>
      </ha-card>
      ${this._styles()}`;

    this._bindEvents(editable);
  }

  /** "Until the next switching point": −/+ while all thermostats run in auto. */
  _quickChangeHtml(stateObjs) {
    if (this._config.quick_change === false || this._config.editable === false) return "";
    const attrs = stateObjs.map((st) => st.attributes || {});
    if (!attrs.length || attrs.some((a) => a.mode_detail !== "auto") || stateObjs.some((st) => st.state === "off")) {
      return "";
    }
    const targets = attrs.map((a) => Number(a.temperature)).filter(Number.isFinite);
    if (!targets.length) return "";
    const same = targets.every((t) => Math.abs(t - targets[0]) < 0.01);
    const shown = this._quick ? this._quick.value : targets[0];
    const temporary = attrs.some((a) => a.week_profile_validation === "temporary_change");
    const nextAt = attrs[0].next_switch_at ? new Date(attrs[0].next_switch_at) : null;
    const nextTemp = attrs[0].next_switch_temperature;
    let until = "";
    if (nextAt) {
      const sameDay = nextAt.toDateString() === new Date().toDateString();
      const time = nextAt.toLocaleTimeString(wLocale, { hour: "2-digit", minute: "2-digit" });
      const day = sameDay ? "" : `${nextAt.toLocaleDateString(wLocale, { weekday: "short" })} `;
      until = WT().untilThen(`${day}${time}`, fmtTemp(nextTemp));
    } else {
      until = WT().untilNext;
    }
    const label = this._quick
      ? WT().sendingSoon
      : temporary
        ? WT().temporary(until)
        : same
          ? WT().byPlan(until)
          : WT().thermostatsDiffer;
    return `<div class="quick${temporary || this._quick ? " active" : ""}">
        <ha-icon icon="${temporary ? "mdi:clock-edit-outline" : "mdi:clock-outline"}"></ha-icon>
        <button class="qbtn" data-quick="-0.5" title="${WT().colder}"><ha-icon icon="mdi:minus"></ha-icon></button>
        <span class="qval">${same || this._quick ? fmtTemp(shown) : "–"}</span>
        <button class="qbtn" data-quick="0.5" title="${WT().warmer}"><ha-icon icon="mdi:plus"></ha-icon></button>
        <span class="qtext">${esc(label)}</span>
        ${temporary && !this._quick ? `<button class="text qreset">${WT().backToPlan}</button>` : ""}
      </div>`;
  }

  _quickStep(delta) {
    const attrs = this._entityIds().map((id) => this._hass.states[id]?.attributes || {});
    const base = this._quick ? this._quick.value : Number(attrs[0]?.temperature);
    if (!Number.isFinite(base)) return;
    const value = Math.min(TEMP_MAX, Math.max(TEMP_MIN + 0.5, Math.round((base + delta) * 2) / 2));
    clearTimeout(this._quick?.timer);
    // collect taps; one radio packet per thermostat once the user stops tapping
    this._quick = { value, timer: setTimeout(() => this._quickSend(), 1200) };
    this._render();
  }

  async _quickSend() {
    const value = this._quick?.value;
    if (value == null) return;
    try {
      for (const entityId of this._entityIds()) {
        await this._hass.callService("climate", "set_temperature", { entity_id: entityId, temperature: value });
      }
    } catch (err) {
      this._quickError = err?.message || String(err);
    } finally {
      this._quick = null;
      this._render();
    }
  }

  async _quickReset() {
    for (const entityId of this._entityIds()) {
      // auto without temperature: the thermostat takes the profile value again
      await this._hass.callService("climate", "set_hvac_mode", { entity_id: entityId, hvac_mode: "auto" });
    }
  }

  /** Other MAX! thermostats whose week profile can be copied, grouped by area. */
  _copySources() {
    const own = new Set(this._entityIds());
    return Object.entries(this._hass?.states || {})
      .filter(
        ([id, st]) =>
          id.startsWith("climate.") &&
          !own.has(id) &&
          st.attributes?.address !== undefined &&
          DAYS.some(([key]) => st.attributes[`week_profile_${key}`])
      )
      .map(([id, st]) => {
        const areaId = this._areaOf(id);
        return {
          id,
          name: st.attributes.friendly_name || id,
          area: (areaId && this._hass.areas?.[areaId]?.name) || WT().noArea,
        };
      })
      .sort((a, b) => a.area.localeCompare(b.area, "de") || a.name.localeCompare(b.name, wLocale));
  }

  _areaOf(entityId) {
    const ent = this._hass?.entities?.[entityId];
    return ent?.area_id || this._hass?.devices?.[ent?.device_id]?.area_id || null;
  }

  /** Temperature sensors usable as room sensor; same area as the thermostat first. */
  _temperatureSensors(areaId) {
    return Object.values(this._hass.states)
      .filter(
        (st) =>
          st.entity_id.startsWith("sensor.") &&
          st.attributes.device_class === "temperature" &&
          ["°C", "°F"].includes(st.attributes.unit_of_measurement) &&
          this._hass.entities?.[st.entity_id]?.platform !== "cul_max"
      )
      .map((st) => ({
        id: st.entity_id,
        name: st.attributes.friendly_name || st.entity_id,
        value: st.state,
        unit: st.attributes.unit_of_measurement,
        sameArea: Boolean(areaId) && this._areaOf(st.entity_id) === areaId,
      }))
      .sort((a, b) => Number(b.sameArea) - Number(a.sameArea) || a.name.localeCompare(b.name, wLocale));
  }

  _sensorRowHtml(stateObjs, shortNames) {
    const supported = stateObjs
      .map((st, idx) => ({ st, name: shortNames[idx] }))
      .filter(({ st }) => st.attributes.external_sensor_supported);
    if (!supported.length) return "";
    const canEdit = this._config.editable !== false;
    const sensorName = (id) => this._hass.states[id]?.attributes?.friendly_name || id;
    const statusText = (a) => {
      const at = a.external_temperature_sent_at
        ? new Date(a.external_temperature_sent_at).toLocaleTimeString(wLocale, { hour: "2-digit", minute: "2-digit" })
        : "";
      switch (a.external_temperature_status) {
        case "active":
          return { level: "ok", text: WT().confirmedAt(at) };
        case "waiting":
          return { level: "info", text: WT().sending };
        case "unconfirmed":
          return { level: "warn", text: WT().unconfirmed };
        case "sensor_stale":
          return { level: "warn", text: WT().sensorStale };
        default:
          return { level: "warn", text: WT().sensorMissing };
      }
    };
    const sensors = [...new Set(supported.map(({ st }) => st.attributes.external_temperature_sensor || ""))];
    let body;
    if (sensors.length === 1 && !sensors[0]) {
      body = `<span>${WT().regulateOn}: <b>${WT().ownSensor}</b></span>`;
    } else {
      body = supported
        .map(({ st, name }) => {
          const a = st.attributes;
          const who = supported.length > 1 ? `${esc(name)}: ` : "";
          if (!a.external_temperature_sensor) return `<div>${who}<b>${WT().ownSensor}</b></div>`;
          const stat = statusText(a);
          return `<div>${who}${WT().regulateOn} <b>${esc(sensorName(a.external_temperature_sensor))}</b>${
            a.external_temperature != null ? ` ${fmtTemp(a.external_temperature)}` : ""
          } <span class="reg-state ${stat.level}">${esc(stat.text)}</span></div>`;
        })
        .join("");
    }
    const ed = this._sensorEdit;
    let editor = "";
    if (ed) {
      const areaId = this._areaOf(supported[0].st.entity_id);
      const options = this._temperatureSensors(areaId)
        .map(
          (x) =>
            `<option value="${esc(x.id)}" ${x.id === ed.value ? "selected" : ""}>${esc(x.name)} (${esc(x.value)} ${esc(
              x.unit
            )})${x.sameArea ? ` · ${WT().sameRoom}` : ""}</option>`
        )
        .join("");
      editor = `
        <div class="reg-editor">
          <select class="reg-select" ${ed.busy ? "disabled" : ""}>
            <option value="" ${!ed.value ? "selected" : ""}>${WT().ownSensorDefault}</option>
            ${options}
          </select>
          <div class="ed-note">${WT().sensorNote(supported.length > 1)}</div>
          ${ed.error ? `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${esc(ed.error)}</span></div>` : ""}
          <div class="ed-actions">
            <button class="text reg-cancel" ${ed.busy ? "disabled" : ""}>${WT().cancel}</button>
            <button class="primary reg-save" ${ed.busy ? "disabled" : ""}>${ed.busy ? WT().settingUp : WT().apply}</button>
          </div>
        </div>`;
    }
    return `
      <div class="reg">
        <ha-icon icon="mdi:home-thermometer-outline"></ha-icon>
        <div class="reg-body">${body}</div>
        ${canEdit && !ed ? `<button class="text reg-edit">${WT().change}</button>` : ""}
      </div>
      ${editor}`;
  }

  async _saveSensor() {
    const ed = this._sensorEdit;
    const select = this.shadowRoot.querySelector(".reg-select");
    ed.value = select ? select.value : ed.value;
    ed.busy = true;
    ed.error = null;
    this._render();
    const targets = this._entityIds().filter(
      (id) => this._hass.states[id]?.attributes?.external_sensor_supported
    );
    try {
      for (const id of targets) {
        await this._hass.callService("cul_max", "set_external_temperature_sensor", {
          entity_id: id,
          sensor_entity_id: ed.value || null,
        });
      }
      this._sensorEdit = null;
    } catch (err) {
      ed.busy = false;
      ed.error = err?.message || String(err);
    }
    this._render();
  }

  _editorHtml(dayKey, longLabel, targetNames = null) {
    const ed = this._editing;
    const tempOptions = (selected) => {
      const options = [];
      for (let t = TEMP_MIN; t <= TEMP_MAX + 0.001; t += 0.5) {
        const label = t <= TEMP_MIN ? WT().offOption : t.toLocaleString(wLocale, { minimumFractionDigits: 1 });
        options.push(`<option value="${t}" ${Math.abs(t - selected) < 0.01 ? "selected" : ""}>${label}</option>`);
      }
      return options.join("");
    };
    const segRows = ed.segments
      .map((seg, idx) => {
        const last = idx === ed.segments.length - 1;
        return `
          <div class="ed-seg" data-idx="${idx}">
            <span class="ed-from">${toHHMM(seg.from)}</span>
            <span class="ed-dash">–</span>
            ${
              last
                ? `<span class="ed-until fixed">24:00</span>`
                : `<input class="ed-until" type="text" inputmode="numeric" maxlength="5" placeholder="hh:mm"
                     aria-label="${WT().untilLabel}" value="${Number.isFinite(seg.until) ? toHHMM(seg.until) : ""}" ${ed.busy ? "disabled" : ""}>`
            }
            <select class="ed-temp" ${ed.busy ? "disabled" : ""}>${tempOptions(seg.temp)}</select>
            <span class="ed-unit">°C</span>
            <button class="icon ed-remove" title="${WT().removeSegment}" ${
              ed.segments.length <= 1 || ed.busy ? "disabled" : ""
            }><ha-icon icon="mdi:close"></ha-icon></button>
          </div>`;
      })
      .join("");
    const copyBoxes = DAYS.filter(([key]) => key !== dayKey)
      .map(
        ([key, short]) =>
          `<label class="copy"><input type="checkbox" data-copy="${key}" ${ed.copyTo.has(key) ? "checked" : ""} ${
            ed.busy ? "disabled" : ""
          }>${short}</label>`
      )
      .join("");
    return `
      <div class="editor">
        <div class="ed-title">${esc(WT().editTitle(longLabel))}${
          targetNames ? `<span class="ed-targets">${esc(WT().forTargets(targetNames.join(" + ")))}</span>` : ""
        }</div>
        <div class="ed-list">${segRows}</div>
        <button class="text ed-add" ${ed.segments.length >= MAX_POINTS || ed.busy ? "disabled" : ""}>
          <ha-icon icon="mdi:plus"></ha-icon>${WT().addPoint}
        </button>
        <div class="ed-copy">
          <span>${WT().alsoApply}</span>
          <div class="copy-days">${copyBoxes}</div>
          <div class="copy-presets">
            <button class="text" data-preset="workdays" ${ed.busy ? "disabled" : ""}>${WT().workdays}</button>
            <button class="text" data-preset="weekend" ${ed.busy ? "disabled" : ""}>${WT().weekend}</button>
            <button class="text" data-preset="all" ${ed.busy ? "disabled" : ""}>${WT().all}</button>
            <button class="text" data-preset="none" ${ed.busy ? "disabled" : ""}>${WT().none}</button>
          </div>
        </div>
        ${this._sourceHtml(ed, longLabel)}
        ${ed.error ? `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${esc(ed.error)}</span></div>` : ""}
        <div class="ed-actions">
          <button class="text ed-cancel" ${ed.busy ? "disabled" : ""}>${WT().cancel}</button>
          <button class="primary ed-save" ${ed.busy ? "disabled" : ""}>
            ${ed.busy ? WT().uploadingProgress(ed.progress) : WT().upload}
          </button>
        </div>
        <div class="ed-note">${WT().radioNote}</div>
      </div>`;
  }

  _sourceHtml(ed, longLabel) {
    if (!ed.source) {
      return `<button class="text small ed-src-open" ${ed.busy ? "disabled" : ""}>${WT().fromOtherRoom}</button>`;
    }
    const sources = this._copySources();
    if (!sources.length) {
      return `<div class="ed-src"><span class="muted">${WT().noOtherThermostat}</span>
        <button class="text small ed-src-close">${WT().close}</button></div>`;
    }
    const src = ed.source;
    if (!src.entity || !sources.some((s) => s.id === src.entity)) src.entity = sources[0].id;
    let groups = "";
    let lastArea = null;
    for (const s of sources) {
      if (s.area !== lastArea) {
        if (lastArea !== null) groups += "</optgroup>";
        groups += `<optgroup label="${esc(s.area)}">`;
        lastArea = s.area;
      }
      groups += `<option value="${esc(s.id)}" ${s.id === src.entity ? "selected" : ""}>${esc(s.name)}</option>`;
    }
    groups += "</optgroup>";
    const attrs = this._hass.states[src.entity]?.attributes || {};
    let preview = "";
    if (src.scope === "week") {
      const unknown = DAYS.filter(([key]) => !attrs[`week_profile_${key}`]).map(([, short]) => short);
      const bars = DAYS.map(([key, short]) => {
        const segs = parseDay(attrs[`week_profile_${key}`]);
        const inner = segs.length
          ? segs
              .map(
                (seg) =>
                  `<div class="mseg" style="left:${(seg.from / 1440) * 100}%;width:${((seg.until - seg.from) / 1440) * 100}%;background:${tempColor(
                    seg.temp
                  )}"></div>`
              )
              .join("")
          : `<div class="mempty">${WT().unknown}</div>`;
        return `<div class="mrow"><span>${short}</span><div class="mbar">${inner}</div></div>`;
      }).join("");
      const targets = this._entityIds().length;
      preview = `<div class="mini">${bars}</div>
        <div class="muted">${WT().weekNote(targets, unknown.join(", "))}</div>`;
    }
    return `<div class="ed-src">
        <div class="ed-src-row">
          <select class="ed-src-entity" ${ed.busy ? "disabled" : ""}>${groups}</select>
          <label><input type="radio" name="srcscope" value="day" ${src.scope !== "week" ? "checked" : ""}> ${esc(WT().onlyDay(longLabel))}</label>
          <label><input type="radio" name="srcscope" value="week" ${src.scope === "week" ? "checked" : ""}> ${WT().wholeWeek}</label>
        </div>
        ${preview}
        <div class="ed-src-row end">
          <button class="text small ed-src-close" ${ed.busy ? "disabled" : ""}>${WT().cancel}</button>
          <button class="text small ed-src-apply" ${ed.busy ? "disabled" : ""}>${
      src.scope === "week" ? WT().sendWholeWeek : WT().intoEditor
    }</button>
        </div>
      </div>`;
  }

  async _applySource() {
    const ed = this._editing;
    const src = ed?.source;
    if (!src?.entity) return;
    const attrs = this._hass.states[src.entity]?.attributes || {};
    if (src.scope !== "week") {
      const segments = parseDay(attrs[`week_profile_${ed.day}`]);
      if (!segments.length) {
        ed.error = WT().dayUnknownThere;
      } else {
        ed.segments = segments.map((seg) => ({ ...seg }));
        ed.source = null;
        ed.error = null;
      }
      this._render();
      return;
    }
    ed.busy = true;
    ed.error = null;
    const targets = this._entityIds();
    try {
      for (let idx = 0; idx < targets.length; idx += 1) {
        const own = this._hass.states[targets[idx]]?.attributes || {};
        const days = {};
        for (const [key] of DAYS) {
          const value = attrs[`week_profile_${key}`];
          // skip unknown days and days that are already identical (saves radio time)
          if (value && serializeDay(parseDay(value)) !== serializeDay(parseDay(own[`week_profile_${key}`]))) {
            days[key] = serializeDay(parseDay(value));
          }
        }
        if (!Object.keys(days).length) continue;
        ed.progress = targets.length > 1 ? `${idx + 1}/${targets.length}` : "";
        this._render();
        await this._hass.callService("cul_max", "set_week_profile_days", { entity_id: targets[idx], ...days });
      }
      this._editing = null;
    } catch (err) {
      ed.busy = false;
      ed.progress = "";
      ed.error = err?.message || String(err);
    }
    this._render();
  }

  _openEditor(dayKey) {
    const attrs = this._stateObj()?.attributes || {};
    const segments = parseDay(attrs[`week_profile_${dayKey}`]).map((s) => ({ ...s }));
    this._editing = {
      day: dayKey,
      segments: segments.length ? segments : this._defaultDay(attrs),
      copyTo: new Set(),
      busy: false,
      error: null,
    };
    this._render();
  }

  /** Starting point for a day whose program is unknown: eco – comfort 06–22 – eco. */
  _defaultDay(attrs) {
    const eco = Number(attrs.eco_temperature) || 17;
    const comfort = Number(attrs.comfort_temperature) || 21;
    return [
      { from: 0, until: 360, temp: eco },
      { from: 360, until: 1320, temp: comfort },
      { from: 1320, until: 1440, temp: eco },
    ];
  }

  _closeEditor() {
    this._editing = null;
    this._render();
  }

  _readEditorInputs() {
    const ed = this._editing;
    if (!ed) return;
    this.shadowRoot.querySelectorAll(".ed-seg").forEach((row) => {
      const idx = Number(row.dataset.idx);
      const seg = ed.segments[idx];
      const until = row.querySelector("input.ed-until");
      if (until) seg.until = toMinutes(until.value.replace(".", ":"));
      const temp = row.querySelector("select.ed-temp");
      if (temp) seg.temp = Number(temp.value);
    });
    // keep "from" consistent with the previous segment's end
    ed.segments.forEach((seg, idx) => {
      seg.from = idx === 0 ? 0 : ed.segments[idx - 1].until;
    });
    ed.segments[ed.segments.length - 1].until = 1440;
  }

  async _save() {
    const ed = this._editing;
    this._readEditorInputs();
    const error = validateDay(ed.segments);
    if (error) {
      ed.error = error;
      this._render();
      return;
    }
    const value = serializeDay(ed.segments);
    const days = { [ed.day]: value };
    ed.copyTo.forEach((key) => {
      days[key] = value;
    });
    const targets = this._entityIds();
    ed.busy = true;
    ed.error = null;
    for (let idx = 0; idx < targets.length; idx += 1) {
      ed.progress = targets.length > 1 ? `${idx + 1}/${targets.length}` : "";
      this._render();
      try {
        // one thermostat after the other: each upload waits for its ACKs
        await this._hass.callService("cul_max", "set_week_profile_days", { entity_id: targets[idx], ...days });
      } catch (err) {
        const name = this._hass.states[targets[idx]]?.attributes?.friendly_name || targets[idx];
        ed.busy = false;
        ed.progress = "";
        ed.error = `${targets.length > 1 ? `${name}: ` : ""}${err?.message || String(err)}`;
        this._render();
        return;
      }
    }
    this._editing = null;
    this._render();
  }

  _bindEvents(editable) {
    const root = this.shadowRoot;
    const openMoreInfo = (entityId) =>
      this.dispatchEvent(
        new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } })
      );
    const menu = root.querySelector(".more-menu");
    root.querySelector(".more")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      // several thermostats: let the user pick which one to open
      if (menu) menu.hidden = !menu.hidden;
      else openMoreInfo(this._entityIds()[0]);
    });
    root.querySelectorAll(".more-item").forEach((item) =>
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        menu.hidden = true;
        openMoreInfo(item.dataset.entity);
      })
    );
    if (menu) {
      root.querySelector("ha-card")?.addEventListener("click", () => {
        menu.hidden = true;
      });
    }
    // tapping a thermostat's status row opens exactly that thermostat
    root.querySelectorAll(".chips.pick").forEach((row) => {
      const open = (ev) => {
        ev.stopPropagation();
        openMoreInfo(row.dataset.entity);
      };
      row.addEventListener("click", open);
      row.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") open(ev);
      });
    });

    if (editable) {
      root.querySelectorAll(".day-row.editable").forEach((row) => {
        const open = () => {
          if (this._editing?.busy) return;
          const day = row.dataset.day;
          if (this._editing?.day === day) this._closeEditor();
          else this._openEditor(day);
        };
        row.addEventListener("click", open);
        row.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            open();
          }
        });
      });
    }

    root.querySelector(".reg-edit")?.addEventListener("click", () => {
      const first = this._entityIds()
        .map((id) => this._hass.states[id])
        .find((st) => st?.attributes?.external_sensor_supported);
      this._sensorEdit = { value: first?.attributes?.external_temperature_sensor || "", busy: false, error: null };
      this._render();
    });
    root.querySelector(".reg-select")?.addEventListener("change", (ev) => {
      if (this._sensorEdit) this._sensorEdit.value = ev.target.value;
    });
    root.querySelector(".reg-cancel")?.addEventListener("click", () => {
      this._sensorEdit = null;
      this._render();
    });
    root.querySelector(".reg-save")?.addEventListener("click", () => this._saveSensor());

    root.querySelectorAll("[data-quick]").forEach((btn) =>
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this._quickStep(Number(btn.dataset.quick));
      })
    );
    root.querySelector(".qreset")?.addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._quickReset();
    });

    const editor = root.querySelector(".editor");
    if (!editor || !this._editing) return;
    const ed = this._editing;

    editor.querySelectorAll("input.ed-until, select.ed-temp").forEach((input) =>
      input.addEventListener("change", () => {
        this._readEditorInputs();
        ed.error = null;
        this._render();
      })
    );
    editor.querySelectorAll(".ed-remove").forEach((button) =>
      button.addEventListener("click", () => {
        this._readEditorInputs();
        const idx = Number(button.closest(".ed-seg").dataset.idx);
        ed.segments.splice(idx, 1);
        ed.segments.forEach((seg, i) => {
          seg.from = i === 0 ? 0 : ed.segments[i - 1].until;
        });
        ed.segments[ed.segments.length - 1].until = 1440;
        this._render();
      })
    );
    editor.querySelector(".ed-add")?.addEventListener("click", () => {
      this._readEditorInputs();
      // Append: split the last segment (… – 24:00) so every time the user
      // already entered stays as it is. Only if that segment is too short,
      // fall back to the longest one.
      const splitAt = (idx) => {
        const seg = ed.segments[idx];
        const mid = Math.round((seg.from + seg.until) / 2 / 5) * 5;
        if (mid <= seg.from || mid >= seg.until) return false;
        ed.segments.splice(idx + 1, 0, { from: mid, until: seg.until, temp: seg.temp });
        seg.until = mid;
        return true;
      };
      let target = ed.segments.length - 1;
      if (ed.segments[target].until - ed.segments[target].from < 10) {
        target = 0;
        ed.segments.forEach((seg, idx) => {
          const a = ed.segments[target];
          if (seg.until - seg.from > a.until - a.from) target = idx;
        });
      }
      if (!splitAt(target)) return;
      this._render();
    });
    editor.querySelectorAll("[data-copy]").forEach((box) =>
      box.addEventListener("change", () => {
        this._readEditorInputs();
        if (box.checked) ed.copyTo.add(box.dataset.copy);
        else ed.copyTo.delete(box.dataset.copy);
      })
    );
    editor.querySelectorAll("[data-preset]").forEach((button) =>
      button.addEventListener("click", () => {
        this._readEditorInputs();
        const presets = {
          workdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
          weekend: ["saturday", "sunday"],
          all: DAYS.map(([key]) => key),
          none: [],
        };
        ed.copyTo = new Set(presets[button.dataset.preset].filter((key) => key !== ed.day));
        this._render();
      })
    );
    editor.querySelector(".ed-src-open")?.addEventListener("click", () => {
      this._readEditorInputs();
      ed.source = { entity: null, scope: "day" };
      this._render();
    });
    editor.querySelector(".ed-src-close")?.addEventListener("click", () => {
      ed.source = null;
      this._render();
    });
    editor.querySelector(".ed-src-entity")?.addEventListener("change", (ev) => {
      ed.source.entity = ev.target.value;
      this._render();
    });
    editor.querySelectorAll('input[name="srcscope"]').forEach((radio) =>
      radio.addEventListener("change", () => {
        this._readEditorInputs();
        ed.source.scope = radio.value;
        this._render();
      })
    );
    editor.querySelector(".ed-src-apply")?.addEventListener("click", () => {
      this._readEditorInputs();
      this._applySource();
    });
    editor.querySelector(".ed-cancel")?.addEventListener("click", () => this._closeEditor());
    editor.querySelector(".ed-save")?.addEventListener("click", () => this._save());
  }

  _styles() {
    return `<style>
      :host { display: block; }
      ha-card { overflow: hidden; }
      .wrapper { padding: 16px; }
      .msg { padding: 16px; line-height: 1.5; }
      .header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
      .title { font-size: 1.1rem; font-weight: 600; line-height: 1.25; }
      .subtitle { color: var(--secondary-text-color); font-size: 0.9rem; margin-top: 2px; }
      .more { margin: -8px -8px 0 0; color: var(--secondary-text-color); }
      .more-wrap { position: relative; }
      .more-menu {
        position: absolute; right: -4px; top: 32px; z-index: 5; min-width: 200px;
        display: flex; flex-direction: column; padding: 4px 0; border-radius: 10px;
        background: var(--card-background-color, #fff); box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        border: 1px solid var(--divider-color);
      }
      .more-menu[hidden] { display: none; }
      .more-item {
        text-align: left; padding: 10px 14px; border: none; background: none; cursor: pointer;
        font: inherit; color: var(--primary-text-color);
      }
      .more-item:hover { background: var(--secondary-background-color); }
      .chips.pick { cursor: pointer; border-radius: 8px; margin-left: -4px; padding-left: 4px; }
      .chips.pick:hover { background: var(--secondary-background-color); }
      .chips.pick:focus-visible { outline: 2px solid var(--primary-color); }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
      .chip {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 3px 10px; border-radius: 999px; font-size: 0.85rem;
        background: var(--secondary-background-color); color: var(--primary-text-color);
      }
      .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
      .chip.mode { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .chips .who { font-size: 0.85rem; font-weight: 600; min-width: 4.5em; align-self: center; }
      .chips + .chips { margin-top: 0; }
      .who-label { font-size: 0.7rem; color: var(--secondary-text-color); margin: 2px 0 1px; }
      .label .diff { margin-left: 3px; color: var(--warning-color, #ffa600); }
      .ed-targets { font-weight: 400; color: var(--secondary-text-color); margin-left: 6px; font-size: 0.85rem; }
      .next {
        display: flex; align-items: center; gap: 6px; margin-top: 6px;
        color: var(--secondary-text-color); font-size: 0.9rem;
      }
      .next ha-icon, .status ha-icon { --mdc-icon-size: 18px; flex: none; }
      .status {
        display: flex; align-items: flex-start; gap: 8px; margin-top: 8px;
        padding: 8px 10px; border-radius: 10px; font-size: 0.9rem; line-height: 1.35;
      }
      .status.info { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
      .status.warn { background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.18); }
      .status.error { background: rgba(var(--rgb-error-color, 219, 68, 55), 0.16); }
      .axis {
        display: flex; justify-content: space-between; margin: 14px 0 2px 40px;
        font-size: 0.72rem; color: var(--secondary-text-color);
      }
      .days { display: grid; gap: 2px; }
      .day-row {
        display: grid; grid-template-columns: 32px 1fr; gap: 8px; align-items: start;
        padding: 4px 4px 2px; margin: 0 -4px; border-radius: 8px;
      }
      .day-row.editable { cursor: pointer; }
      .day-row.editable:hover, .day-row.editing { background: var(--secondary-background-color); }
      .day-row:focus-visible { outline: 2px solid var(--primary-color); }
      .label { font-weight: 600; color: var(--secondary-text-color); line-height: 26px; font-size: 0.9rem; }
      .today .label { color: var(--primary-color); }
      .bar {
        position: relative; height: 26px; border-radius: 6px; overflow: hidden;
        background: var(--secondary-background-color);
      }
      .seg {
        position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center;
        color: #fff; font-size: 0.76rem; font-weight: 600; white-space: nowrap; overflow: hidden;
        border-right: 1px solid var(--card-background-color, #fff); box-sizing: border-box;
        opacity: 0.88;
      }
      .today .seg { opacity: 1; }
      .seg.active { box-shadow: inset 0 0 0 2px rgba(255,255,255,0.85); }
      .now {
        position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px;
        background: var(--primary-text-color); box-shadow: 0 0 0 1px var(--card-background-color, #fff);
      }
      .empty { padding: 4px 8px; font-style: italic; color: var(--secondary-text-color); font-size: 0.85rem; }
      .times { position: relative; height: 14px; font-size: 0.68rem; color: var(--secondary-text-color); }
      .times span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
      .times.two { height: 26px; }
      .times span.l1 { top: 12px; }
      .reg {
        display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 0.9rem;
        color: var(--primary-text-color);
      }
      .reg > ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); flex: none; }
      .reg-body { flex: 1; display: grid; gap: 2px; }
      .reg-state { font-size: 0.8rem; padding: 1px 6px; border-radius: 6px; margin-left: 4px; }
      .reg-state.ok { background: rgba(var(--rgb-success-color, 67, 160, 71), 0.18); }
      .reg-state.info { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.14); }
      .reg-state.warn { background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.2); }
      .reg-editor {
        margin: 6px 0 4px 26px; padding: 10px; border-radius: 10px; border: 1px solid var(--divider-color);
      }
      .reg-select {
        width: 100%; font: inherit; padding: 6px 8px; border-radius: 6px;
        border: 1px solid var(--divider-color); background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .hint { margin-top: 8px; font-size: 0.78rem; color: var(--secondary-text-color); text-align: right; }
      .editor {
        margin: 2px 0 10px 40px; padding: 12px; border-radius: 10px;
        border: 1px solid var(--divider-color); background: var(--card-background-color);
      }
      .ed-title { font-weight: 600; margin-bottom: 8px; }
      .ed-list { display: grid; gap: 6px; }
      .ed-seg { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
      .ed-from, .ed-until.fixed { min-width: 44px; font-variant-numeric: tabular-nums; }
      .ed-dash, .ed-unit { color: var(--secondary-text-color); }
      input.ed-until { width: 4.2em; text-align: center; font-variant-numeric: tabular-nums; }
      input.ed-until, select.ed-temp {
        font: inherit; padding: 4px 6px; border-radius: 6px;
        border: 1px solid var(--divider-color); background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      button {
        font: inherit; cursor: pointer; border: none; border-radius: 8px;
        display: inline-flex; align-items: center; gap: 4px;
      }
      button:disabled { opacity: 0.45; cursor: default; }
      button ha-icon { --mdc-icon-size: 18px; }
      button.icon { background: none; color: var(--secondary-text-color); padding: 4px; }
      button.text { background: none; color: var(--primary-color); padding: 6px 8px; }
      button.primary {
        background: var(--primary-color); color: var(--text-primary-color, #fff); padding: 8px 14px; font-weight: 600;
      }
      .ed-add { margin-top: 6px; }
      .ed-copy { margin-top: 10px; font-size: 0.9rem; }
      .quick { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 6px;
        font-size: 0.9rem; color: var(--secondary-text-color); }
      .quick ha-icon { --mdc-icon-size: 18px; }
      .quick.active .qval { color: var(--primary-color); }
      .qbtn { width: 28px; height: 28px; border-radius: 50%; border: none; cursor: pointer; display: inline-flex;
        align-items: center; justify-content: center; background: var(--secondary-background-color);
        color: var(--primary-text-color); }
      .qbtn ha-icon { --mdc-icon-size: 16px; }
      .qval { font-weight: 600; color: var(--primary-text-color); min-width: 3.6em; text-align: center; }
      .qtext { flex: 1; min-width: 10em; }
      .text.small { font-size: 0.82rem; padding: 4px 6px; }
      .ed-src-open { margin-top: 6px; }
      .ed-src { margin-top: 10px; padding: 10px; border-radius: 10px; border: 1px dashed var(--divider-color); font-size: 0.88rem; }
      .ed-src-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
      .ed-src-row.end { justify-content: flex-end; margin-top: 6px; }
      .ed-src select { flex: 1; min-width: 12em; height: 34px; border-radius: 8px; border: 1px solid var(--divider-color);
        background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
      .muted { color: var(--secondary-text-color); font-size: 0.8rem; }
      .mini { display: grid; gap: 3px; margin: 8px 0 4px; }
      .mrow { display: grid; grid-template-columns: 24px 1fr; gap: 6px; align-items: center; font-size: 0.75rem;
        color: var(--secondary-text-color); }
      .mbar { position: relative; height: 10px; border-radius: 3px; overflow: hidden; background: var(--secondary-background-color); }
      .mseg { position: absolute; top: 0; bottom: 0; }
      .mempty { font-size: 0.65rem; line-height: 10px; padding-left: 4px; font-style: italic; }
      .ed-copy > span { color: var(--secondary-text-color); }
      .copy-days { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0 2px; }
      .copy { display: inline-flex; align-items: center; gap: 4px; }
      .copy-presets { display: flex; flex-wrap: wrap; gap: 2px; margin-left: -8px; }
      .ed-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
      .ed-note { margin-top: 8px; font-size: 0.75rem; color: var(--secondary-text-color); }
    </style>`;
  }
}

if (!customElements.get("cul-max-week-profile-card")) {
  customElements.define("cul-max-week-profile-card", CulMaxWeekProfileCard);
}

class CulMaxWeekProfileCardEditor extends HTMLElement {
  setConfig(config) {
    const cfg = { show_current_temp: true, editable: true, ...config };
    // normalise: first thermostat in "entity", further ones in "entities"
    if (Array.isArray(cfg.entities) && cfg.entities.length) {
      const ids = cfg.entities.map((e) => (typeof e === "string" ? e : e?.entity)).filter(Boolean);
      cfg.entity = cfg.entity || ids[0];
    }
    this._config = cfg;
    this._render();
  }

  _extraIds() {
    const ids = (this._config.entities || []).map((e) => (typeof e === "string" ? e : e?.entity));
    return ids.filter((id) => id && id !== this._config.entity);
  }

  _withExtras(config, extras) {
    const next = { ...config };
    if (extras.length) next.entities = [next.entity, ...extras];
    else delete next.entities;
    return next;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    wSetLang(hass);
    if (first) this._render();
  }

  _availableEntities() {
    return Object.entries(this._hass?.states || {})
      .filter(([entityId, state]) => CulMaxWeekProfileCard._isCulMaxClimate(entityId, state))
      .map(([entityId, state]) => ({ entity_id: entityId, label: state.attributes.friendly_name || entityId }))
      .sort((a, b) => a.label.localeCompare(b.label, wLocale));
  }

  _emitConfig(config) {
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  _render() {
    if (!this._config) return;
    const options = this._availableEntities()
      .map(
        (entry) =>
          `<option value="${esc(entry.entity_id)}" ${entry.entity_id === this._config.entity ? "selected" : ""}>${esc(
            entry.label
          )}</option>`
      )
      .join("");
    this.innerHTML = `
      <div class="cmwp-editor">
        <label><span>Thermostat</span>
          <select data-field="entity"><option value="">${WT().pick}</option>${options}</select>
        </label>
        <div class="extras"><span>${WT().moreThermostats}</span>
          ${this._availableEntities()
            .filter((entry) => entry.entity_id !== this._config.entity)
            .map(
              (entry) => `<label class="checkbox"><input type="checkbox" data-extra="${esc(entry.entity_id)}" ${
                this._extraIds().includes(entry.entity_id) ? "checked" : ""
              }/><span>${esc(entry.label)}</span></label>`
            )
            .join("")}
        </div>
        <label><span>${WT().titleLabel}</span>
          <input data-field="title" type="text" value="${esc(this._config.title || "")}" />
        </label>
        <label class="checkbox">
          <input data-field="show_current_temp" type="checkbox" ${this._config.show_current_temp ? "checked" : ""} />
          <span>${WT().showCurrent}</span>
        </label>
        <label class="checkbox">
          <input data-field="editable" type="checkbox" ${this._config.editable !== false ? "checked" : ""} />
          <span>${WT().allowEdit}</span>
        </label>
      </div>
      <style>
        .cmwp-editor { display: grid; gap: 12px; padding: 8px 0; }
        .cmwp-editor label { display: grid; gap: 6px; }
        .cmwp-editor label > span { color: var(--secondary-text-color); font-size: 0.9rem; }
        .cmwp-editor input[type="text"], .cmwp-editor select {
          padding: 8px 10px; border-radius: 8px; border: 1px solid var(--divider-color);
          background: var(--card-background-color); color: var(--primary-text-color); font: inherit;
        }
        .cmwp-editor .checkbox { display: flex; align-items: center; gap: 10px; }
        .cmwp-editor .checkbox > span { color: var(--primary-text-color); }
        .cmwp-editor .extras { display: grid; gap: 4px; max-height: 180px; overflow: auto; }
        .cmwp-editor .extras > span { color: var(--secondary-text-color); font-size: 0.9rem; }
      </style>`;

    const stop = (event) => event.stopPropagation();
    const root = this.querySelector(".cmwp-editor");
    ["click", "mousedown", "mouseup", "touchstart"].forEach((type) => root?.addEventListener(type, stop));

    this.querySelector('[data-field="entity"]')?.addEventListener("change", (ev) => {
      const entity = ev.target.value;
      this._emitConfig(this._withExtras({ ...this._config, entity }, this._extraIds().filter((id) => id !== entity)));
      this._render();
    });
    this.querySelectorAll("[data-extra]").forEach((box) =>
      box.addEventListener("change", () => {
        const extras = this._extraIds().filter((id) => id !== box.dataset.extra);
        if (box.checked) extras.push(box.dataset.extra);
        this._emitConfig(this._withExtras(this._config, extras));
      })
    );
    this.querySelector('[data-field="title"]')?.addEventListener("input", (ev) =>
      this._emitConfig({ ...this._config, title: ev.target.value })
    );
    this.querySelector('[data-field="show_current_temp"]')?.addEventListener("change", (ev) =>
      this._emitConfig({ ...this._config, show_current_temp: ev.target.checked })
    );
    this.querySelector('[data-field="editable"]')?.addEventListener("change", (ev) =>
      this._emitConfig({ ...this._config, editable: ev.target.checked })
    );
  }
}

if (!customElements.get("cul-max-week-profile-card-editor")) {
  customElements.define("cul-max-week-profile-card-editor", CulMaxWeekProfileCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-week-profile-card")) {
  window.customCards.push({
    type: "cul-max-week-profile-card",
    name: "CUL MAX Week Profile",
    description: "Week program card for MAX! thermostats with timeline, status and editing",
    preview: true,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}

// exported for tests (no effect in the browser)
if (typeof module !== "undefined") {
  module.exports = { parseDay, serializeDay, validateDay, toMinutes, toHHMM };
}
