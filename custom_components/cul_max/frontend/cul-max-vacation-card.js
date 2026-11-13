/*
 * CUL MAX! vacation card
 *
 * Enter the return date/time, vacation temperature and preheat time and start
 * the vacation for the whole flat (cul_max.start_vacation). While a vacation
 * is running it shows until when, which thermostats confirmed and lets you
 * change or end it (cul_max.end_vacation).
 *
 * Summer mode (cul_max.start_summer / end_summer) lives in the same card:
 * a collapsed section starts it; while it runs the card shows only summer.
 */

const VAC_TEMP_MIN = 4.5;
const VAC_TEMP_MAX = 30.5;
const PREHEAT_OPTIONS = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12];
const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

// UI language: German for "de*", English for everything else.
let vLang = "de";
let vLocale = "de-DE";
const vSetLang = (hass) => {
  const language = String(hass?.locale?.language || hass?.language || "en");
  vLang = language.toLowerCase().startsWith("de") ? "de" : "en";
  vLocale = vLang === "de" ? "de-DE" : language.includes("-") ? language : "en-GB";
};
const V_TEXT = {
  de: {
    title: "Urlaub",
    enterDateTime: "Bitte Datum und Uhrzeit (hh:mm) angeben.",
    returnInFuture: "Die Rückkehr (abzüglich Vorheizen) muss in der Zukunft liegen.",
    noSwitch: "Kein MAX!-Urlaubsschalter gefunden. Ist die Integration „MAX! via CUL“ ab Version 0.5 eingerichtet?",
    vacationActive: "Urlaub aktiv – ganze Wohnung",
    normal: "Heizung normal im Wochenprogramm",
    change: "Ändern",
    endVacation: "Urlaub beenden",
    notReached: (c, t, names) => `${c} von ${t} Thermostaten bestätigt – noch nicht erreicht: ${names} (wird automatisch wiederholt)`,
    sendingProgress: (c, t) => `Wird übertragen … ${c} von ${t} Thermostaten bestätigt`,
    allSummer: (t) => `Alle ${t} Thermostate sind im Sommermodus`,
    allVacation: (t) => `Alle ${t} Thermostate haben den Urlaub bestätigt`,
    thermostats: "Thermostate",
    since: "seit",
    summerStays: "Die Thermostate bleiben so, bis du den Sommermodus beendest. Die wöchentliche Entkalkungsfahrt läuft weiter, Raumthermometer senden nichts, ein Urlaub ist gesperrt.",
    sending: "Wird gesendet …",
    endSummer: "Sommermodus beenden",
    summer: "Sommermodus",
    summerPause: "Heizpause",
    summerRestoring: (n) => `Sommermodus beendet – ${n} Thermostat(e) werden zurückgesetzt …`,
    summerLink: "Sommermodus …",
    summerExplain: "Heizsaison vorbei? Alle Thermostate gehen dauerhaft auf <b>Aus</b> (Ventil zu) oder <b>Ein</b> (Ventil ganz offen, entlastet das Ventil – nur bei abgeschalteter Heizung sinnvoll), bis du den Sommermodus beendest. Danach geht jedes Thermostat zurück in seinen Zustand von vorher.",
    cancel: "Abbrechen",
    startSummer: "Sommermodus starten",
    returnAt: "Rückkehr",
    temperature: "Temperatur",
    backAt: (when, preheat) => `Thermostate gehen ${when} zurück ins Wochenprogramm${preheat ? ` (${preheat} h Vorheizen)` : ""} – auch ohne Home Assistant.`,
    vacationRestoring: (n) => `Urlaub beendet – ${n} Thermostat(e) werden zurückgesetzt …`,
    restoreFailed: (n) => `${n} Thermostat(e) konnten noch nicht zurückgesetzt werden (wird wiederholt).`,
    formHint: (when, rounded) => `Thermostate gehen ${when} zurück ins Wochenprogramm${rounded ? " (MAX! kennt nur volle und halbe Stunden)" : ""}.`,
    preheatBefore: (h) => `${h} h vorher`,
    noPreheat: "kein Vorheizen",
    returnOn: "Rückkehr am",
    at: "um",
    colder: "kälter",
    warmer: "wärmer",
    preheat: "Vorheizen",
    applyChange: "Änderung übernehmen",
    startVacation: "Urlaub starten",
    valves: {
      closed: { label: "Aus – Ventil zu", short: "Heizung aus, Ventile zu" },
      open: { label: "Ein – Ventil ganz offen", short: "Ventile ganz offen" },
    },
    editorTitle: "Titel",
  },
  en: {
    title: "Vacation",
    enterDateTime: "Please enter date and time (hh:mm).",
    returnInFuture: "The return (minus preheating) must be in the future.",
    noSwitch: "No MAX! vacation switch found. Is the integration \"MAX! via CUL\" 0.5 or newer set up?",
    vacationActive: "Vacation active – whole home",
    normal: "Heating normal on the week program",
    change: "Change",
    endVacation: "End vacation",
    notReached: (c, t, names) => `${c} of ${t} thermostats confirmed – not reached yet: ${names} (retried automatically)`,
    sendingProgress: (c, t) => `Sending … ${c} of ${t} thermostats confirmed`,
    allSummer: (t) => `All ${t} thermostats are in summer mode`,
    allVacation: (t) => `All ${t} thermostats confirmed the vacation`,
    thermostats: "Thermostats",
    since: "since",
    summerStays: "The thermostats stay like this until you end summer mode. Their weekly decalcification keeps running, room thermometers send nothing, a vacation is blocked.",
    sending: "Sending …",
    endSummer: "End summer mode",
    summer: "Summer mode",
    summerPause: "Heating paused",
    summerRestoring: (n) => `Summer mode ended – restoring ${n} thermostat(s) …`,
    summerLink: "Summer mode …",
    summerExplain: "Heating season over? All thermostats go to <b>Off</b> (valve closed) or <b>On</b> (valve fully open, relieves the valve – only sensible with the boiler switched off) until you end summer mode. Afterwards every thermostat returns to its previous state.",
    cancel: "Cancel",
    startSummer: "Start summer mode",
    returnAt: "Return",
    temperature: "Temperature",
    backAt: (when, preheat) => `Thermostats return to their week program ${when}${preheat ? ` (${preheat} h preheating)` : ""} – even without Home Assistant.`,
    vacationRestoring: (n) => `Vacation ended – restoring ${n} thermostat(s) …`,
    restoreFailed: (n) => `${n} thermostat(s) could not be restored yet (retrying).`,
    formHint: (when, rounded) => `Thermostats return to their week program ${when}${rounded ? " (MAX! only knows full and half hours)" : ""}.`,
    preheatBefore: (h) => `${h} h before`,
    noPreheat: "no preheating",
    returnOn: "Return on",
    at: "at",
    colder: "colder",
    warmer: "warmer",
    preheat: "Preheating",
    applyChange: "Apply change",
    startVacation: "Start vacation",
    valves: {
      closed: { label: "Off – valve closed", short: "heating off, valves closed" },
      open: { label: "On – valve fully open", short: "valves fully open" },
    },
    editorTitle: "Title",
  },
};
const VT = () => V_TEXT[vLang];

const vEsc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

const pad2 = (n) => String(n).padStart(2, "0");
const fmtNum = (value) =>
  Number(value).toLocaleString(vLocale, { minimumFractionDigits: 0, maximumFractionDigits: 1 });
const fmtWhen = (date) =>
  vLang === "de"
    ? `${WEEKDAYS[date.getDay()]}, ${pad2(date.getDate())}.${pad2(date.getMonth() + 1)}. ${pad2(date.getHours())}:${pad2(
        date.getMinutes()
      )}`
    : date.toLocaleString(vLocale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const toDateInput = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
const toTimeInput = (date) => `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
const floorHalfHour = (date) => {
  const d = new Date(date.getTime());
  d.setMinutes(d.getMinutes() < 30 ? 0 : 30, 0, 0);
  return d;
};
const parseLocal = (day, time) => {
  const dm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day || "");
  const tm = /^(\d{1,2})[:.](\d{2})$/.exec((time || "").trim());
  if (!dm || !tm) return null;
  const h = Number(tm[1]);
  const m = Number(tm[2]);
  if (h > 23 || m > 59) return null;
  return new Date(Number(dm[1]), Number(dm[2]) - 1, Number(dm[3]), h, m, 0, 0);
};

const SUMMER_VALVE_KEYS = ["closed", "open"];

class CulMaxVacationCard extends HTMLElement {
  static _isVacationSwitch(entityId, stateObj) {
    return entityId?.startsWith("switch.") && stateObj?.attributes && "thermostats_until" in stateObj.attributes;
  }

  static _isSummerSwitch(entityId, stateObj) {
    return entityId?.startsWith("switch.") && stateObj?.attributes && "summer_valve" in stateObj.attributes;
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find((id) => CulMaxVacationCard._isVacationSwitch(id, hass.states[id])) || "";
    return { entity };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._form = null;
    this._editing = false;
    this._busy = false;
    this._error = "";
    this._signature = "";
    this._summerOpen = false;
    this._summerValve = null;
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._signature = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    vSetLang(hass);
    const st = this._stateObj();
    const su = this._summerObj();
    const signature = JSON.stringify([vLang, st ? [st.state, st.attributes] : null, su ? [su.state, su.attributes] : null]);
    if (signature !== this._signature) {
      this._signature = signature;
      this._render();
    }
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  _entityId() {
    if (this._config?.entity) return this._config.entity;
    const states = this._hass?.states || {};
    return Object.keys(states).find((id) => CulMaxVacationCard._isVacationSwitch(id, states[id])) || "";
  }

  _stateObj() {
    const id = this._entityId();
    return id ? this._hass?.states?.[id] : undefined;
  }

  _summerObj() {
    const states = this._hass?.states || {};
    const id =
      this._config?.summer_entity ||
      Object.keys(states).find((sid) => CulMaxVacationCard._isSummerSwitch(sid, states[sid])) ||
      "";
    return id ? states[id] : undefined;
  }

  _initForm(attrs) {
    const now = new Date();
    let end = attrs.return_at ? new Date(attrs.return_at) : null;
    if (!end || Number.isNaN(end.getTime()) || end <= now) {
      end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 7, 18, 0, 0, 0);
    }
    this._form = {
      day: toDateInput(end),
      time: toTimeInput(end),
      temperature: Number(attrs.temperature ?? 16),
      preheat: Number(attrs.preheat_hours ?? 0),
    };
  }

  _formEnd() {
    return this._form ? parseLocal(this._form.day, this._form.time) : null;
  }

  _validate() {
    const end = this._formEnd();
    if (!end) return { error: VT().enterDateTime };
    const deviceEnd = floorHalfHour(new Date(end.getTime() - this._form.preheat * 3600 * 1000));
    if (deviceEnd.getTime() <= Date.now() + 5 * 60 * 1000) {
      return { error: VT().returnInFuture };
    }
    return { end, deviceEnd };
  }

  _render() {
    if (!this._config || !this._hass) return;
    vSetLang(this._hass);
    const T = VT();
    const st = this._stateObj();
    if (!st) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="msg">${vEsc(T.noSwitch)}</div></ha-card>`;
      return;
    }
    const attrs = st.attributes;
    const active = st.state === "on";
    const summer = this._summerObj();
    if (summer?.state === "on") {
      this._renderSummer(summer.attributes);
      return;
    }
    if (!this._form) this._initForm(attrs);
    const showForm = !active || this._editing;

    const header = `
      <div class="header">
        <ha-icon class="hicon ${active ? "on" : ""}" icon="${active ? "mdi:airplane" : "mdi:airplane-off"}"></ha-icon>
        <div>
          <div class="title">${vEsc(
            // the old default title was stored in the card config: translate it too
            !this._config.title || this._config.title === V_TEXT.de.title ? T.title : this._config.title
          )}</div>
          <div class="subtitle">${active ? T.vacationActive : T.normal}</div>
        </div>
      </div>`;

    let body = "";
    if (active) body += this._activeSummary(attrs);
    else body += this._restoreNote(attrs) + (summer ? this._summerRestoreNote(summer.attributes) : "");
    if (showForm) body += this._formHtml(active);
    else
      body += `<div class="actions">
          <button class="ghost" data-action="edit" ${this._busy ? "disabled" : ""}>${T.change}</button>
          <button class="primary danger" data-action="end" ${this._busy ? "disabled" : ""}>${T.endVacation}</button>
        </div>`;
    if (summer && !active) body += this._summerSection(summer.attributes);
    if (this._error) body += `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${vEsc(this._error)}</span></div>`;

    this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="wrapper">${header}${body}</div></ha-card>`;
    this._bind();
  }

  _renderSummer(attrs) {
    const T = VT();
    const valve = SUMMER_VALVE_KEYS.includes(attrs.summer_valve) ? attrs.summer_valve : "closed";
    const total = Object.keys(attrs.devices || {}).length;
    const confirmed = attrs.confirmed || 0;
    const failedNames = Object.entries(attrs.devices || {})
      .filter(([, status]) => status === "failed")
      .map(([name]) => name);
    let delivery;
    if (failedNames.length) {
      delivery = `<div class="status warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${VT().notReached(
        confirmed,
        total,
        vEsc(failedNames.join(", "))
      )}</span></div>`;
    } else if (attrs.pending) {
      delivery = `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>${VT().sendingProgress(confirmed, total)}</span></div>`;
    } else {
      delivery = `<div class="status ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><span>${VT().allSummer(total)}</span></div>`;
    }
    const since = attrs.started_at ? new Date(attrs.started_at) : null;
    const body = `
      <div class="big">
        <div class="tile"><span class="lbl">${T.thermostats}</span><span class="val">${vEsc(T.valves[valve].label)}</span></div>
        <div class="tile"><span class="lbl">${T.since}</span><span class="val">${since ? vEsc(fmtWhen(since)) : "–"}</span></div>
      </div>
      <div class="hint"><ha-icon icon="mdi:information-outline"></ha-icon><span>${T.summerStays}</span></div>
      ${delivery}
      <div class="actions">
        <button class="primary" data-action="summer-end" ${this._busy ? "disabled" : ""}>${
          this._busy ? T.sending : T.endSummer
        }</button>
      </div>`;
    const header = `
      <div class="header">
        <ha-icon class="hicon on" icon="mdi:white-balance-sunny"></ha-icon>
        <div>
          <div class="title">${T.summer}</div>
          <div class="subtitle">${T.summerPause} – ${vEsc(T.valves[valve].short)}</div>
        </div>
      </div>`;
    const error = this._error
      ? `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${vEsc(this._error)}</span></div>`
      : "";
    this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="wrapper">${header}${body}${error}</div></ha-card>`;
    this._bind();
  }

  _summerRestoreNote(attrs) {
    const restoring = attrs.restoring || 0;
    if (!restoring) return "";
    return `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>${VT().summerRestoring(restoring)}</span></div>`;
  }

  _summerSection(attrs) {
    const T = VT();
    if (!this._summerOpen) {
      return `<div class="summer-toggle"><button class="link" data-action="summer-open">
        <ha-icon icon="mdi:white-balance-sunny"></ha-icon><span>${T.summerLink}</span></button></div>`;
    }
    const valve = this._summerValve || (SUMMER_VALVE_KEYS.includes(attrs.summer_valve) ? attrs.summer_valve : "closed");
    const choice = SUMMER_VALVE_KEYS.map(
      (key) =>
        `<button class="seg ${key === valve ? "sel" : ""}" data-valve="${key}" ${this._busy ? "disabled" : ""}>${vEsc(
          T.valves[key].label
        )}</button>`
    ).join("");
    return `
      <div class="summer">
        <div class="summer-title"><ha-icon icon="mdi:white-balance-sunny"></ha-icon><span>${T.summer}</span></div>
        <div class="hint"><ha-icon icon="mdi:information-outline"></ha-icon><span>${T.summerExplain}</span></div>
        <div class="segs">${choice}</div>
        <div class="actions">
          <button class="ghost" data-action="summer-close" ${this._busy ? "disabled" : ""}>${T.cancel}</button>
          <button class="primary" data-action="summer-start" ${this._busy ? "disabled" : ""}>${
            this._busy ? T.sending : T.startSummer
          }</button>
        </div>
      </div>`;
  }

  _activeSummary(attrs) {
    const ret = attrs.return_at ? new Date(attrs.return_at) : null;
    const back = attrs.thermostats_until ? new Date(attrs.thermostats_until) : null;
    const total = Object.keys(attrs.devices || {}).length;
    const confirmed = attrs.confirmed || 0;
    const failed = attrs.failed || 0;
    const pending = attrs.pending || 0;
    const failedNames = Object.entries(attrs.devices || {})
      .filter(([, status]) => status === "failed")
      .map(([name]) => name);
    let delivery;
    if (failed) {
      delivery = `<div class="status warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${VT().notReached(
        confirmed,
        total,
        vEsc(failedNames.join(", "))
      )}</span></div>`;
    } else if (pending) {
      delivery = `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>${VT().sendingProgress(confirmed, total)}</span></div>`;
    } else {
      delivery = `<div class="status ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><span>${VT().allVacation(total)}</span></div>`;
    }
    const preheat = Number(attrs.preheat_hours || 0);
    return `
      <div class="big">
        <div class="tile"><span class="lbl">${VT().returnAt}</span><span class="val">${ret ? vEsc(fmtWhen(ret)) : "–"}</span></div>
        <div class="tile"><span class="lbl">${VT().temperature}</span><span class="val">${fmtNum(attrs.temperature ?? 16)} °C</span></div>
      </div>
      ${
        back
          ? `<div class="hint"><ha-icon icon="mdi:radiator"></ha-icon><span>${VT().backAt(
              vEsc(fmtWhen(back)),
              preheat ? fmtNum(preheat) : ""
            )}</span></div>`
          : ""
      }
      ${delivery}`;
  }

  _restoreNote(attrs) {
    const statuses = Object.values(attrs.devices || {});
    const restoring = statuses.filter((s) => s === "restoring").length;
    const failed = statuses.filter((s) => s === "restore_failed").length;
    if (restoring)
      return `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>${VT().vacationRestoring(restoring)}</span></div>`;
    if (failed)
      return `<div class="status warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${VT().restoreFailed(failed)}</span></div>`;
    return "";
  }

  _formHintText(check) {
    if (check.error) return check.error;
    const wanted = new Date(check.end.getTime() - this._form.preheat * 3600 * 1000);
    const rounded = wanted.getTime() !== check.deviceEnd.getTime();
    return VT().formHint(fmtWhen(check.deviceEnd), rounded);
  }

  _formHtml(active) {
    const T = VT();
    const f = this._form;
    const check = this._validate();
    const preheatOptions = PREHEAT_OPTIONS.map(
      (h) => `<option value="${h}" ${h === f.preheat ? "selected" : ""}>${h ? T.preheatBefore(fmtNum(h)) : T.noPreheat}</option>`
    ).join("");
    const info = `<div class="hint ${check.error ? "warn" : ""}"><ha-icon icon="mdi:information-outline"></ha-icon><span>${vEsc(
      this._formHintText(check)
    )}</span></div>`;
    return `
      <div class="form">
        <label class="field"><span>${T.returnOn}</span>
          <input type="date" data-field="day" value="${vEsc(f.day)}" ${this._busy ? "disabled" : ""}></label>
        <label class="field"><span>${T.at}</span>
          <input type="text" inputmode="numeric" placeholder="hh:mm" maxlength="5" data-field="time" value="${vEsc(f.time)}" ${
            this._busy ? "disabled" : ""
          }></label>
        <div class="field"><span>${T.temperature}</span>
          <div class="stepper">
            <button data-step="-0.5" aria-label="${T.colder}" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
            <span class="tval">${fmtNum(f.temperature)} °C</span>
            <button data-step="0.5" aria-label="${T.warmer}" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
          </div></div>
        <label class="field"><span>${T.preheat}</span>
          <select data-field="preheat" ${this._busy ? "disabled" : ""}>${preheatOptions}</select></label>
      </div>
      ${info}
      <div class="actions">
        ${active ? `<button class="ghost" data-action="cancel" ${this._busy ? "disabled" : ""}>${T.cancel}</button>` : ""}
        <button class="primary" data-action="start" ${this._busy || check.error ? "disabled" : ""}>
          ${this._busy ? T.sending : active ? T.applyChange : T.startVacation}</button>
      </div>`;
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-field]").forEach((el) => {
      const handler = () => {
        const key = el.dataset.field;
        this._form[key] = key === "preheat" ? Number(el.value) : el.value;
        this._error = "";
        this._refreshFormHints();
      };
      el.addEventListener("input", handler);
      el.addEventListener("change", handler);
    });
    root.querySelectorAll("[data-step]").forEach((el) =>
      el.addEventListener("click", () => {
        const next = Math.round((this._form.temperature + Number(el.dataset.step)) * 2) / 2;
        this._form.temperature = Math.min(VAC_TEMP_MAX, Math.max(VAC_TEMP_MIN, next));
        const out = root.querySelector(".tval");
        if (out) out.textContent = `${fmtNum(this._form.temperature)} °C`;
      })
    );
    root.querySelector('[data-action="start"]')?.addEventListener("click", () => this._start());
    root.querySelector('[data-action="summer-open"]')?.addEventListener("click", () => {
      this._summerOpen = true;
      this._render();
    });
    root.querySelector('[data-action="summer-close"]')?.addEventListener("click", () => {
      this._summerOpen = false;
      this._summerValve = null;
      this._render();
    });
    root.querySelectorAll("[data-valve]").forEach((el) =>
      el.addEventListener("click", () => {
        this._summerValve = el.dataset.valve;
        this._render();
      })
    );
    root.querySelector('[data-action="summer-start"]')?.addEventListener("click", () =>
      this._summerCall("start_summer", { valve: this._summerValve || this._summerObj()?.attributes?.summer_valve || "closed" })
    );
    root.querySelector('[data-action="summer-end"]')?.addEventListener("click", () => this._summerCall("end_summer", {}));
    root.querySelector('[data-action="end"]')?.addEventListener("click", () => this._end());
    root.querySelector('[data-action="edit"]')?.addEventListener("click", () => {
      this._editing = true;
      this._initForm(this._stateObj()?.attributes || {});
      this._render();
    });
    root.querySelector('[data-action="cancel"]')?.addEventListener("click", () => {
      this._editing = false;
      this._error = "";
      this._render();
    });
  }

  /** Update hint + start button without re-rendering the inputs (keeps focus). */
  _refreshFormHints() {
    const root = this.shadowRoot;
    const check = this._validate();
    const hint = root.querySelector(".form + .hint");
    if (hint) {
      hint.classList.toggle("warn", Boolean(check.error));
      hint.querySelector("span").textContent = this._formHintText(check);
    }
    const start = root.querySelector('[data-action="start"]');
    if (start) start.disabled = this._busy || Boolean(check.error);
  }

  async _start() {
    const check = this._validate();
    if (check.error) return;
    const end = check.end;
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("cul_max", "start_vacation", {
        temperature: this._form.temperature,
        end: `${toDateInput(end)} ${toTimeInput(end)}`,
        preheat_hours: this._form.preheat,
      });
      this._editing = false;
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _summerCall(service, data) {
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("cul_max", service, data);
      this._summerOpen = false;
      this._summerValve = null;
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _end() {
    this._busy = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("cul_max", "end_vacation", {});
      this._form = null;
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _style() {
    return `<style>
      :host { display: block; }
      .wrapper { padding: 16px; }
      .msg { padding: 16px; line-height: 1.5; }
      .header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
      .hicon { --mdc-icon-size: 28px; color: var(--secondary-text-color); }
      .hicon.on { color: var(--primary-color); }
      .title { font-size: 1.1rem; font-weight: 600; line-height: 1.25; }
      .subtitle { color: var(--secondary-text-color); font-size: 0.9rem; margin-top: 2px; }
      .big { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
      .tile {
        display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border-radius: 12px;
        background: var(--secondary-background-color);
      }
      .lbl { font-size: 0.75rem; color: var(--secondary-text-color); }
      .val { font-size: 1.15rem; font-weight: 600; white-space: nowrap; }
      .form { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }
      .field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
      .field > span { font-size: 0.8rem; color: var(--secondary-text-color); }
      input, select {
        box-sizing: border-box; width: 100%; min-width: 0; height: 40px; padding: 0 10px;
        border-radius: 8px; border: 1px solid var(--divider-color);
        background: var(--card-background-color); color: var(--primary-text-color); font: inherit;
        color-scheme: light dark;
      }
      input:focus, select:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
      .stepper {
        display: flex; align-items: center; justify-content: space-between; height: 40px;
        border-radius: 8px; border: 1px solid var(--divider-color); padding: 0 4px; box-sizing: border-box;
      }
      .stepper button {
        width: 32px; height: 32px; border-radius: 50%; border: none; cursor: pointer;
        background: var(--secondary-background-color); color: var(--primary-text-color);
        display: inline-flex; align-items: center; justify-content: center;
      }
      .stepper ha-icon { --mdc-icon-size: 18px; }
      .tval { font-weight: 600; }
      .hint, .status {
        display: flex; align-items: flex-start; gap: 8px; margin-top: 10px; font-size: 0.88rem; line-height: 1.35;
        color: var(--secondary-text-color);
      }
      .hint.warn { color: var(--warning-color, #ffa600); }
      .hint ha-icon, .status ha-icon { --mdc-icon-size: 18px; flex: none; }
      .status { padding: 8px 10px; border-radius: 10px; color: var(--primary-text-color); }
      .status.info { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
      .status.ok { background: rgba(var(--rgb-success-color, 67, 160, 71), 0.14); }
      .status.warn { background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.18); }
      .status.error { background: rgba(var(--rgb-error-color, 219, 68, 55), 0.16); }
      .actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 14px; }
      .primary {
        height: 40px; padding: 0 18px; border: none; border-radius: 20px; cursor: pointer; font: inherit; font-weight: 600;
        background: var(--primary-color); color: var(--text-primary-color, #fff);
      }
      .primary.danger { background: var(--error-color, #db4437); }
      .primary:disabled { opacity: 0.5; cursor: default; }
      .ghost {
        height: 40px; padding: 0 14px; border: none; border-radius: 20px; cursor: pointer; font: inherit; font-weight: 600;
        background: transparent; color: var(--primary-color);
      }
      .ghost:hover { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.1); }
      .summer-toggle { display: flex; justify-content: flex-start; margin-top: 12px; }
      .link {
        display: inline-flex; align-items: center; gap: 6px; padding: 4px 6px; border: none; border-radius: 8px;
        background: transparent; color: var(--secondary-text-color); cursor: pointer; font: inherit; font-size: 0.88rem;
      }
      .link:hover { color: var(--primary-color); }
      .link ha-icon { --mdc-icon-size: 18px; }
      .summer { margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
      .summer-title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
      .summer-title ha-icon { --mdc-icon-size: 20px; color: var(--warning-color, #ffa600); }
      .segs { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
      .seg {
        min-height: 40px; padding: 6px 10px; border-radius: 10px; cursor: pointer; font: inherit; font-size: 0.88rem;
        border: 1px solid var(--divider-color); background: transparent; color: var(--primary-text-color);
      }
      .seg.sel { border-color: var(--primary-color); background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); font-weight: 600; }
      @media (max-width: 420px) { .form, .segs { grid-template-columns: 1fr; } }
    </style>`;
  }
}

class CulMaxVacationCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    this._rendered = true;
    const switches = Object.keys(this._hass.states).filter((id) =>
      CulMaxVacationCard._isVacationSwitch(id, this._hass.states[id])
    );
    this.innerHTML = `
      <div style="display:grid;gap:12px;padding:8px 0">
        <label style="display:grid;gap:6px"><span>${V_TEXT[vLang].editorTitle}</span>
          <input data-field="title" value="${vEsc(this._config.title ?? "")}"
            style="padding:8px 10px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)"></label>
        ${
          switches.length > 1
            ? `<label style="display:grid;gap:6px"><span>CUL</span><select data-field="entity">${switches
                .map((id) => `<option value="${id}" ${id === this._config.entity ? "selected" : ""}>${vEsc(id)}</option>`)
                .join("")}</select></label>`
            : ""
        }
      </div>`;
    this.querySelectorAll("[data-field]").forEach((el) =>
      el.addEventListener("change", () => {
        this._config = { ...this._config, [el.dataset.field]: el.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      })
    );
  }
}

CulMaxVacationCard.getConfigElement = () => document.createElement("cul-max-vacation-card-editor");

if (!customElements.get("cul-max-vacation-card")) {
  customElements.define("cul-max-vacation-card", CulMaxVacationCard);
}
if (!customElements.get("cul-max-vacation-card-editor")) {
  customElements.define("cul-max-vacation-card-editor", CulMaxVacationCardEditor);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-vacation-card")) {
  window.customCards.push({
    type: "cul-max-vacation-card",
    name: "CUL MAX vacation",
    description: "Vacation and summer mode for all MAX! thermostats: return, temperature, preheating, status",
    preview: true,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}
