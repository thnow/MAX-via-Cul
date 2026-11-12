/*
 * CUL MAX! pairing card
 *
 * Opens the pairing window on a chosen CUL, shows a countdown and lists the
 * devices that answered in this session – new or already known – plus the
 * ones that were ignored because they still belong to another central. Every
 * new device gets a suggested name from its type and area; name, area and
 * "link with the room" are saved in one step (cul_max/pairing/save).
 */

const pEsc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

const TYPE_INFO = {
  HeatingThermostat: { label: "Thermostat", icon: "mdi:radiator", hint: "Boost-Taste ca. 3 s drücken" },
  HeatingThermostatPlus: { label: "Thermostat", icon: "mdi:radiator", hint: "Boost-Taste ca. 3 s drücken" },
  WallMountedThermostat: { label: "Wandthermostat", icon: "mdi:thermostat", hint: "Boost-Taste ca. 3 s drücken" },
  ShutterContact: { label: "Fensterkontakt", icon: "mdi:window-closed-variant", hint: "Anlerntaste ca. 3 s drücken" },
  PushButton: { label: "Taster", icon: "mdi:gesture-tap-button", hint: "beide Tasten ca. 3 s drücken" },
};

const DURATIONS = [60, 120, 300];

class CulMaxPairingCard extends HTMLElement {
  static getStubConfig() {
    return { title: "MAX! anlernen" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._gateway = null;
    this._duration = 60;
    this._forms = {}; // address -> {name, area, link, nameEdited, saving, saved, error}
    this._error = "";
    this._tick = null;
  }

  setConfig(config) {
    this._config = { title: "MAX! anlernen", ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
  }

  connectedCallback() {
    if (!this._focusHooked) {
      this._focusHooked = true;
      this.shadowRoot.addEventListener("focusout", () =>
        setTimeout(() => {
          const active = this.shadowRoot.activeElement;
          if (this._pendingRender && !(active && active.matches("input, select"))) {
            this._pendingRender = false;
            this._render();
          }
        }, 0)
      );
    }
    if (this._hass && !this._unsub) this._subscribe();
    this._tick = setInterval(() => this._updateCountdown(), 1000);
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
    clearInterval(this._tick);
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _subscribe() {
    if (!this._hass?.connection || this._unsub) return;
    this._unsub = this._hass.connection
      .subscribeMessage(
        (event) => {
          this._data = event;
          this._error = "";
          // do not re-render while the user is typing a name / choosing an area
          const active = this.shadowRoot.activeElement;
          if (active && active.matches("input, select")) {
            this._pendingRender = true;
            this._updateCountdown();
            return;
          }
          this._render();
        },
        { type: "cul_max/pairing/subscribe" }
      )
      .catch((err) => {
        this._error = err?.message || "Anlernen nicht verfügbar (Integration ab 0.6.2 nötig)";
        this._unsub = null;
        this._render();
      });
  }

  _gw() {
    const gateways = this._data?.gateways || [];
    return gateways.find((g) => g.entry_id === this._gateway) || gateways[0] || null;
  }

  _areas() {
    return Object.values(this._hass?.areas || {}).sort((a, b) => a.name.localeCompare(b.name, "de"));
  }

  _suggestName(type, areaId, deviceId) {
    const label = (TYPE_INFO[type] || {}).label || type || "Gerät";
    const area = areaId ? this._hass.areas?.[areaId]?.name : "";
    const base = area ? `${label} ${area}` : label;
    const taken = new Set(
      Object.values(this._hass?.devices || {})
        .filter((d) => d.id !== deviceId)
        .map((d) => (d.name_by_user || d.name || "").trim())
    );
    if (!taken.has(base)) return base;
    for (let n = 2; n < 50; n += 1) if (!taken.has(`${base} ${n}`)) return `${base} ${n}`;
    return base;
  }

  _form(device) {
    if (!this._forms[device.address]) {
      const reg = device.device_id ? this._hass.devices?.[device.device_id] : null;
      const area = reg?.area_id || "";
      const autoNamed = !reg?.name_by_user && /^(HeatingThermostat|WallMountedThermostat|ShutterContact|PushButton)/.test(device.name || "");
      this._forms[device.address] = {
        area,
        name: autoNamed || !device.already_known ? this._suggestName(device.device_type, area, device.device_id) : reg?.name_by_user || device.name,
        nameEdited: false,
        link: !device.already_known,
      };
    }
    return this._forms[device.address];
  }

  async _start() {
    const gw = this._gw();
    try {
      await this._hass.callWS({ type: "cul_max/pairing/start", entry_id: gw.entry_id, duration: this._duration });
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    }
  }

  async _stop() {
    try {
      await this._hass.callWS({ type: "cul_max/pairing/stop", entry_id: this._gw().entry_id });
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    }
  }

  async _save(address) {
    const form = this._forms[address];
    form.saving = true;
    form.error = "";
    form.saved = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "cul_max/pairing/save",
        entry_id: this._gw().entry_id,
        address,
        name: form.name,
        area_id: form.area || null,
        link_room: Boolean(form.link && form.area),
      });
      form.saved = result.room === "started"
        ? "Gespeichert – Verknüpfung im Raum läuft (siehe Funk-Warteschlange)"
        : result.room_error
          ? `Gespeichert – ${result.room_error}`
          : "Gespeichert";
    } catch (err) {
      form.error = err?.message || String(err);
    } finally {
      form.saving = false;
      this._render();
    }
  }

  _updateCountdown() {
    const el = this.shadowRoot.querySelector(".countdown");
    const gw = this._gw();
    if (!el || !gw?.active || !gw.until) return;
    const left = Math.max(0, Math.round((new Date(gw.until) - Date.now()) / 1000));
    el.textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  }

  _deviceHtml(device) {
    const info = TYPE_INFO[device.device_type] || { label: device.device_type, icon: "mdi:help-circle-outline" };
    const form = this._form(device);
    const areaOptions = [`<option value="">– kein Bereich –</option>`]
      .concat(
        this._areas().map(
          (a) => `<option value="${pEsc(a.area_id)}" ${a.area_id === form.area ? "selected" : ""}>${pEsc(a.name)}</option>`
        )
      )
      .join("");
    return `<div class="dev" data-address="${pEsc(device.address)}">
        <div class="devhead">
          <ha-icon icon="${info.icon}"></ha-icon>
          <div>
            <div class="devtitle">${pEsc(info.label)} <span class="badge ${device.already_known ? "known" : "new"}">${
      device.already_known ? "bereits bekannt" : "neu"
    }</span></div>
            <div class="sub">Seriennummer ${pEsc(device.serial_number || "–")}</div>
          </div>
        </div>
        <div class="grid">
          <label><span>Name</span><input data-f="name" value="${pEsc(form.name)}" ${form.saving ? "disabled" : ""}></label>
          <label><span>Bereich</span><select data-f="area" ${form.saving ? "disabled" : ""}>${areaOptions}</select></label>
        </div>
        <label class="check"><input type="checkbox" data-f="link" ${form.link ? "checked" : ""} ${
      form.saving || !form.area ? "disabled" : ""
    }> mit den MAX!-Geräten im Bereich verknüpfen (Gruppe und Verknüpfungen)</label>
        <div class="actions">
          ${form.saved ? `<span class="ok">${pEsc(form.saved)}</span>` : ""}
          ${form.error ? `<span class="err">${pEsc(form.error)}</span>` : ""}
          <button class="primary" data-save ${form.saving ? "disabled" : ""}>${form.saving ? "Speichert …" : "Übernehmen"}</button>
        </div>
      </div>`;
  }

  _render() {
    if (!this._config) return;
    const gateways = this._data?.gateways || [];
    const gw = this._gw();
    let body;
    if (this._error && !this._data) body = `<div class="msg">${pEsc(this._error)}</div>`;
    else if (!gw) body = `<div class="msg">Lade …</div>`;
    else {
      const gwSelect =
        gateways.length > 1
          ? `<label class="gwsel"><span>CUL</span><select data-gw>${gateways
              .map((g) => `<option value="${pEsc(g.entry_id)}" ${g.entry_id === gw.entry_id ? "selected" : ""}>${pEsc(g.gateway)}</option>`)
              .join("")}</select></label>`
          : "";
      const control = gw.active
        ? `<div class="active">
             <div class="pulse"></div>
             <div class="atext"><b>Anlernmodus aktiv</b> – noch <span class="countdown"></span><br>
               <span class="sub">Am Gerät: Thermostat/Wandthermostat Boost-Taste, Fensterkontakt Anlerntaste jeweils ca. 3 s drücken.</span></div>
             <button class="ghost" data-stop>Beenden</button>
           </div>`
        : `<div class="start">
             <select data-duration>${DURATIONS.map(
               (d) => `<option value="${d}" ${d === this._duration ? "selected" : ""}>${d < 120 ? `${d} s` : `${d / 60} min`}</option>`
             ).join("")}</select>
             <button class="primary" data-start>Anlernen starten</button>
           </div>`;
      const devices = (gw.devices || []).map((d) => this._deviceHtml(d)).join("");
      const rejected = (gw.rejected || [])
        .map(
          (r) => `<div class="rej"><ha-icon icon="mdi:link-off"></ha-icon><span>Gerät <b>${pEsc(r.address)}</b> gehört noch zu
            einer anderen Zentrale (${pEsc(r.central)}) und wurde nicht übernommen. Gerät zurücksetzen (Batterien raus,
            Boost- bzw. Anlerntaste beim Einlegen gedrückt halten) und erneut anlernen.</span></div>`
        )
        .join("");
      const listTitle = gw.started_at
        ? `<div class="ltitle">In dieser Sitzung gefunden</div>`
        : "";
      body = `${gwSelect}${control}
        ${this._error ? `<div class="err">${pEsc(this._error)}</div>` : ""}
        ${devices || rejected ? `${listTitle}${devices}${rejected}` : gw.active ? `<div class="msg">Noch kein Gerät gemeldet …</div>` : ""}`;
    }
    this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="wrapper">
        <div class="header"><ha-icon icon="mdi:link-plus"></ha-icon><div class="title">${pEsc(this._config.title)}</div></div>
        ${body}</div></ha-card>`;
    this._bind();
    this._updateCountdown();
  }

  _bind() {
    const root = this.shadowRoot;
    root.querySelector("[data-gw]")?.addEventListener("change", (ev) => {
      this._gateway = ev.target.value;
      this._render();
    });
    root.querySelector("[data-duration]")?.addEventListener("change", (ev) => {
      this._duration = Number(ev.target.value);
    });
    root.querySelector("[data-start]")?.addEventListener("click", () => this._start());
    root.querySelector("[data-stop]")?.addEventListener("click", () => this._stop());
    root.querySelectorAll(".dev").forEach((el) => {
      const address = el.dataset.address;
      const form = this._forms[address];
      const device = (this._gw()?.devices || []).find((d) => d.address === address);
      el.querySelector('[data-f="name"]')?.addEventListener("input", (ev) => {
        form.name = ev.target.value;
        form.nameEdited = true;
      });
      el.querySelector('[data-f="area"]')?.addEventListener("change", (ev) => {
        form.area = ev.target.value;
        if (!form.nameEdited && device) form.name = this._suggestName(device.device_type, form.area, device.device_id);
        if (!form.area) form.link = false;
        this._render();
      });
      el.querySelector('[data-f="link"]')?.addEventListener("change", (ev) => {
        form.link = ev.target.checked;
      });
      el.querySelector("[data-save]")?.addEventListener("click", () => this._save(address));
    });
  }

  _style() {
    return `<style>
      :host { display: block; }
      .wrapper { padding: 16px; }
      .header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
      .header ha-icon { color: var(--secondary-text-color); }
      .title { font-size: 1.1rem; font-weight: 600; }
      .msg { padding: 8px 0; color: var(--secondary-text-color); }
      .sub { font-size: 0.8rem; color: var(--secondary-text-color); }
      select, input:not([type]) , input[data-f="name"] {
        box-sizing: border-box; width: 100%; height: 38px; padding: 0 10px; border-radius: 8px;
        border: 1px solid var(--divider-color); background: var(--card-background-color);
        color: var(--primary-text-color); font: inherit; color-scheme: light dark;
      }
      .gwsel { display: grid; gap: 4px; margin-bottom: 10px; }
      .gwsel span, .grid span { font-size: 0.8rem; color: var(--secondary-text-color); }
      .start { display: flex; gap: 8px; align-items: center; }
      .start select { width: auto; }
      .active { display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 12px;
        background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
      .atext { flex: 1; line-height: 1.4; }
      .pulse { width: 12px; height: 12px; border-radius: 50%; background: var(--primary-color); flex: none;
        animation: pulse 1.2s infinite ease-in-out; }
      @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.35; transform: scale(0.7); } }
      .ltitle { margin: 14px 0 6px; font-weight: 600; font-size: 0.9rem; }
      .dev { padding: 12px; border-radius: 12px; background: var(--secondary-background-color); margin-top: 8px; }
      .devhead { display: flex; align-items: center; gap: 10px; }
      .devhead ha-icon { color: var(--primary-color); }
      .devtitle { font-weight: 600; }
      .badge { font-size: 0.72rem; font-weight: 600; padding: 1px 8px; border-radius: 999px; margin-left: 6px; }
      .badge.new { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .badge.known { background: var(--divider-color); color: var(--primary-text-color); }
      .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
      .grid label { display: grid; gap: 4px; }
      .check { display: flex; gap: 8px; align-items: center; margin-top: 8px; font-size: 0.88rem; }
      .actions { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
      .ok { color: var(--success-color, #43a047); font-size: 0.85rem; }
      .err { color: var(--error-color, #db4437); font-size: 0.85rem; }
      .rej { display: flex; gap: 8px; margin-top: 8px; padding: 10px 12px; border-radius: 12px; font-size: 0.88rem;
        background: rgba(var(--rgb-warning-color, 255, 166, 0), 0.18); }
      .rej ha-icon { flex: none; --mdc-icon-size: 20px; }
      .primary { height: 38px; padding: 0 18px; border: none; border-radius: 19px; cursor: pointer; font: inherit;
        font-weight: 600; background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .primary:disabled { opacity: 0.5; cursor: default; }
      .ghost { height: 36px; padding: 0 14px; border: none; border-radius: 18px; cursor: pointer; font: inherit;
        font-weight: 600; background: transparent; color: var(--primary-color); }
      @media (max-width: 420px) { .grid { grid-template-columns: 1fr; } }
    </style>`;
  }
}

if (!customElements.get("cul-max-pairing-card")) {
  customElements.define("cul-max-pairing-card", CulMaxPairingCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-pairing-card")) {
  window.customCards.push({
    type: "cul-max-pairing-card",
    name: "CUL MAX Anlernen",
    description: "MAX!-Geräte anlernen: Countdown, gefundene Geräte, Namensvorschlag, Bereich und Verknüpfung",
    preview: false,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}
