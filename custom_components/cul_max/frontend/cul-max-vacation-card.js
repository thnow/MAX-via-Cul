/*
 * CUL MAX! vacation card
 *
 * Enter the return date/time, vacation temperature and preheat time and start
 * the vacation for the whole flat (cul_max.start_vacation). While a vacation
 * is running it shows until when, which thermostats confirmed and lets you
 * change or end it (cul_max.end_vacation).
 */

const VAC_TEMP_MIN = 4.5;
const VAC_TEMP_MAX = 30.5;
const PREHEAT_OPTIONS = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12];
const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

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
  Number(value).toLocaleString("de-DE", { minimumFractionDigits: 0, maximumFractionDigits: 1 });
const fmtWhen = (date) =>
  `${WEEKDAYS[date.getDay()]}, ${pad2(date.getDate())}.${pad2(date.getMonth() + 1)}. ${pad2(date.getHours())}:${pad2(
    date.getMinutes()
  )}`;
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

class CulMaxVacationCard extends HTMLElement {
  static _isVacationSwitch(entityId, stateObj) {
    return entityId?.startsWith("switch.") && stateObj?.attributes && "thermostats_until" in stateObj.attributes;
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find((id) => CulMaxVacationCard._isVacationSwitch(id, hass.states[id])) || "";
    return { entity, title: "Urlaub" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._form = null;
    this._editing = false;
    this._busy = false;
    this._error = "";
    this._signature = "";
  }

  setConfig(config) {
    this._config = { title: "Urlaub", ...(config || {}) };
    this._signature = "";
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = this._stateObj();
    const signature = JSON.stringify(st ? [st.state, st.attributes] : null);
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
    if (!end) return { error: "Bitte Datum und Uhrzeit (hh:mm) angeben." };
    const deviceEnd = floorHalfHour(new Date(end.getTime() - this._form.preheat * 3600 * 1000));
    if (deviceEnd.getTime() <= Date.now() + 5 * 60 * 1000) {
      return { error: "Die Rückkehr (abzüglich Vorheizen) muss in der Zukunft liegen." };
    }
    return { end, deviceEnd };
  }

  _render() {
    if (!this._config || !this._hass) return;
    const st = this._stateObj();
    if (!st) {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="msg">
        Kein MAX!-Urlaubsschalter gefunden. Ist die Integration „MAX! via CUL“ ab Version 0.5 eingerichtet?
      </div></ha-card>`;
      return;
    }
    const attrs = st.attributes;
    const active = st.state === "on";
    if (!this._form) this._initForm(attrs);
    const showForm = !active || this._editing;

    const header = `
      <div class="header">
        <ha-icon class="hicon ${active ? "on" : ""}" icon="${active ? "mdi:airplane" : "mdi:airplane-off"}"></ha-icon>
        <div>
          <div class="title">${vEsc(this._config.title)}</div>
          <div class="subtitle">${active ? "Urlaub aktiv – ganze Wohnung" : "Heizung normal im Wochenprogramm"}</div>
        </div>
      </div>`;

    let body = "";
    if (active) body += this._activeSummary(attrs);
    else body += this._restoreNote(attrs);
    if (showForm) body += this._formHtml(active);
    else
      body += `<div class="actions">
          <button class="ghost" data-action="edit" ${this._busy ? "disabled" : ""}>Ändern</button>
          <button class="primary danger" data-action="end" ${this._busy ? "disabled" : ""}>Urlaub beenden</button>
        </div>`;
    if (this._error) body += `<div class="status error"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${vEsc(this._error)}</span></div>`;

    this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="wrapper">${header}${body}</div></ha-card>`;
    this._bind();
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
      delivery = `<div class="status warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${confirmed} von ${total} Thermostaten bestätigt – noch nicht erreicht: ${vEsc(
        failedNames.join(", ")
      )} (wird automatisch wiederholt)</span></div>`;
    } else if (pending) {
      delivery = `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>Wird übertragen … ${confirmed} von ${total} Thermostaten bestätigt</span></div>`;
    } else {
      delivery = `<div class="status ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><span>Alle ${total} Thermostate haben den Urlaub bestätigt</span></div>`;
    }
    const preheat = Number(attrs.preheat_hours || 0);
    return `
      <div class="big">
        <div class="tile"><span class="lbl">Rückkehr</span><span class="val">${ret ? vEsc(fmtWhen(ret)) : "–"}</span></div>
        <div class="tile"><span class="lbl">Temperatur</span><span class="val">${fmtNum(attrs.temperature ?? 16)} °C</span></div>
      </div>
      ${
        back
          ? `<div class="hint"><ha-icon icon="mdi:radiator"></ha-icon><span>Thermostate gehen ${vEsc(fmtWhen(back))} zurück ins Wochenprogramm${
              preheat ? ` (${fmtNum(preheat)} h Vorheizen)` : ""
            } – auch ohne Home Assistant.</span></div>`
          : ""
      }
      ${delivery}`;
  }

  _restoreNote(attrs) {
    const statuses = Object.values(attrs.devices || {});
    const restoring = statuses.filter((s) => s === "restoring").length;
    const failed = statuses.filter((s) => s === "restore_failed").length;
    if (restoring)
      return `<div class="status info"><ha-icon icon="mdi:upload-network-outline"></ha-icon><span>Urlaub beendet – ${restoring} Thermostat(e) werden zurückgesetzt …</span></div>`;
    if (failed)
      return `<div class="status warn"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${failed} Thermostat(e) konnten noch nicht zurückgesetzt werden (wird wiederholt).</span></div>`;
    return "";
  }

  _formHintText(check) {
    if (check.error) return check.error;
    const wanted = new Date(check.end.getTime() - this._form.preheat * 3600 * 1000);
    const rounded = wanted.getTime() !== check.deviceEnd.getTime();
    return `Thermostate gehen ${fmtWhen(check.deviceEnd)} zurück ins Wochenprogramm${
      rounded ? " (MAX! kennt nur volle und halbe Stunden)" : ""
    }.`;
  }

  _formHtml(active) {
    const f = this._form;
    const check = this._validate();
    const preheatOptions = PREHEAT_OPTIONS.map(
      (h) => `<option value="${h}" ${h === f.preheat ? "selected" : ""}>${h ? `${fmtNum(h)} h vorher` : "kein Vorheizen"}</option>`
    ).join("");
    const info = `<div class="hint ${check.error ? "warn" : ""}"><ha-icon icon="mdi:information-outline"></ha-icon><span>${vEsc(
      this._formHintText(check)
    )}</span></div>`;
    return `
      <div class="form">
        <label class="field"><span>Rückkehr am</span>
          <input type="date" data-field="day" value="${vEsc(f.day)}" ${this._busy ? "disabled" : ""}></label>
        <label class="field"><span>um</span>
          <input type="text" inputmode="numeric" placeholder="hh:mm" maxlength="5" data-field="time" value="${vEsc(f.time)}" ${
            this._busy ? "disabled" : ""
          }></label>
        <div class="field"><span>Temperatur</span>
          <div class="stepper">
            <button data-step="-0.5" aria-label="kälter" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
            <span class="tval">${fmtNum(f.temperature)} °C</span>
            <button data-step="0.5" aria-label="wärmer" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
          </div></div>
        <label class="field"><span>Vorheizen</span>
          <select data-field="preheat" ${this._busy ? "disabled" : ""}>${preheatOptions}</select></label>
      </div>
      ${info}
      <div class="actions">
        ${active ? `<button class="ghost" data-action="cancel" ${this._busy ? "disabled" : ""}>Abbrechen</button>` : ""}
        <button class="primary" data-action="start" ${this._busy || check.error ? "disabled" : ""}>
          ${this._busy ? "Wird gesendet …" : active ? "Änderung übernehmen" : "Urlaub starten"}</button>
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
      @media (max-width: 420px) { .form { grid-template-columns: 1fr; } }
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
        <label style="display:grid;gap:6px"><span>Titel</span>
          <input data-field="title" value="${vEsc(this._config.title ?? "Urlaub")}"
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
    name: "CUL MAX Urlaub",
    description: "Urlaubsmodus für alle MAX!-Thermostate: Rückkehr, Temperatur, Vorheizen, Status",
    preview: true,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}
