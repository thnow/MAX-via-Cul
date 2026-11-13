/*
 * CUL MAX! transmission queue card
 *
 * Shows what is waiting for radio time (1 % duty cycle): send budget, an
 * estimate until everything is out, the queued commands in plain words and
 * pending configuration per device. Commands can be removed from the queue.
 * Data comes from the websocket subscription cul_max/queue/subscribe – no
 * extra radio traffic.
 */

const qEsc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

// UI language: the profile language if this card has texts for it, else
// English (see TRANSLATING.md).
const Q_TEXT = {
  de: {
    days: ["Sa", "So", "Mo", "Di", "Mi", "Do", "Fr"],
    weekProfile: (day, part) => `Wochenprogramm ${day} (Teil ${part})`,
    tempUntilNext: (t) => `Temperatur ${t} (bis zum nächsten Schaltpunkt)`,
    backToProgram: "Zurück zum Wochenprogramm",
    vacation: (t, until) => `Urlaub ${t}${until ? ` bis ${until}` : ""}`,
    tempManual: (t) => `Temperatur ${t} (manuell)`,
    temperature: "Temperatur",
    roomSensor: (m, d) => `Raumfühler ${m} (Soll ${d})`,
    virtualContact: (open) => `Virtueller Fensterkontakt: ${open ? "offen" : "geschlossen"}`,
    setTime: "Uhrzeit stellen",
    addLink: "Verknüpfung anlegen",
    removeLink: "Verknüpfung entfernen",
    setGroup: "Gruppe setzen",
    removeGroup: "Gruppe entfernen",
    tempConfig: "Temperatur-Einstellungen",
    wake: "Wecken",
    states: { queued: "wartet", waiting_credit: "wartet auf Sendezeit", sending: "wird gesendet", waiting_ack: "wartet auf Bestätigung" },
    priorities: { interactive: "Bedienung", user: "Einstellung", background: "Hintergrund" },
    title: "Funk-Warteschlange",
    unavailable: "Warteschlange nicht verfügbar (Integration ab 0.6.2 nötig)",
    confirmClear: (name) => `Alles, was für „${name}“ noch wartet, verwerfen?`,
    doneIn: (d) => `fertig in etwa ${d}`,
    sendingSoon: "wird gleich gesendet",
    nothing: "nichts zu senden",
    attempt: (a, max) => `Versuch ${a}/${max}`,
    since: (d) => `seit ${d}`,
    superseded: "wird ersetzt",
    removeCmd: "Aus der Warteschlange entfernen",
    nextAttempt: (t) => `nächster Versuch ${t}`,
    packets: (n) => `${n} Paket${n === 1 ? "" : "e"} Konfiguration`,
    next: (what) => `als Nächstes ${what}`,
    attempts: (n) => `${n} Versuch(e)`,
    discardPending: "Ausstehende Konfiguration verwerfen",
    notConnected: "nicht verbunden",
    budget: "Sendebudget",
    allSent: "Alles übertragen",
    loading: "Lade …",
    hint: "Der CUL darf nur 1 % der Zeit senden (36 s pro Stunde, etwa 1 s pro Paket). Größere Änderungen gehen deshalb nach und nach raus.",
  },
  en: {
    days: ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"],
    weekProfile: (day, part) => `Week program ${day} (part ${part})`,
    tempUntilNext: (t) => `Temperature ${t} (until the next switching point)`,
    backToProgram: "Back to the week program",
    vacation: (t, until) => `Vacation ${t}${until ? ` until ${until}` : ""}`,
    tempManual: (t) => `Temperature ${t} (manual)`,
    temperature: "Temperature",
    roomSensor: (m, d) => `Room sensor ${m} (target ${d})`,
    virtualContact: (open) => `Virtual window contact: ${open ? "open" : "closed"}`,
    setTime: "Set clock",
    addLink: "Create link",
    removeLink: "Remove link",
    setGroup: "Set group",
    removeGroup: "Remove group",
    tempConfig: "Temperature settings",
    wake: "Wake up",
    states: { queued: "waiting", waiting_credit: "waiting for radio time", sending: "sending", waiting_ack: "waiting for confirmation" },
    priorities: { interactive: "control", user: "setting", background: "background" },
    title: "Radio queue",
    unavailable: "Queue not available (integration 0.6.2 or newer needed)",
    confirmClear: (name) => `Discard everything still waiting for "${name}"?`,
    doneIn: (d) => `done in about ${d}`,
    sendingSoon: "sending shortly",
    nothing: "nothing to send",
    attempt: (a, max) => `attempt ${a}/${max}`,
    since: (d) => `for ${d}`,
    superseded: "being replaced",
    removeCmd: "Remove from the queue",
    nextAttempt: (t) => `next attempt ${t}`,
    packets: (n) => `${n} configuration packet${n === 1 ? "" : "s"}`,
    next: (what) => `next ${what}`,
    attempts: (n) => `${n} attempt(s)`,
    discardPending: "Discard pending configuration",
    notConnected: "not connected",
    budget: "Send budget",
    allSent: "Everything sent",
    loading: "Loading …",
    hint: "The CUL may only transmit 1 % of the time (36 s per hour, about 1 s per packet). Larger changes therefore go out bit by bit.",
  },
};

/** Language of the user profile if this card has texts for it, else English. */
const qLang = (hass) => {
  const language = String(hass?.locale?.language || hass?.language || "en").toLowerCase();
  const base = language.split("-")[0];
  return Q_TEXT[language] ? language : Q_TEXT[base] ? base : "en";
};
/** Texts of one language; missing entries fall back to English. */
const qText = (lang) => ({ ...Q_TEXT.en, ...(Q_TEXT[lang] || {}) });

const qTemp = (value, locale = "de-DE") =>
  `${Number(value).toLocaleString(locale, { minimumFractionDigits: 0, maximumFractionDigits: 1 })} °C`;

/** Technical command description → short text in the UI language. */
function describe(text, lang = "de", locale = undefined) {
  const L = qText(lang);
  const loc = locale || (lang === "en" ? "en-GB" : lang);
  const temp = (v) => qTemp(v, loc);
  const t = String(text || "");
  let m;
  if ((m = /ConfigWeekProfile \S+ day=(\d) part=(\d)/.exec(t))) {
    return L.weekProfile(L.days[Number(m[1])] || m[1], Number(m[2]) + 1);
  }
  if ((m = /SetTemperature (\d+(?:\.\d+)?) mode=(\w+)(?: until=([\d-]+ [\d:]+))?/.exec(t))) {
    const value = Number(m[1]);
    if (m[2] === "auto") return value > 0 ? L.tempUntilNext(temp(value)) : L.backToProgram;
    if (m[2] === "vacation") return L.vacation(temp(value), m[3]);
    if (m[2] === "boost") return "Boost";
    return L.tempManual(temp(value));
  }
  if (/^SetTemperature/.test(t)) return L.temperature;
  if ((m = /Ist (\d+(?:\.\d+)?) \(extern\), Soll (\d+(?:\.\d+)?)/.exec(t))) {
    return L.roomSensor(temp(m[1]), temp(m[2]));
  }
  if ((m = /VirtualShutterContactState (open|closed)/.exec(t))) return L.virtualContact(m[1] === "open");
  if (/TimeInformation/.test(t)) return L.setTime;
  if (/AddLinkPartner/.test(t)) return L.addLink;
  if (/RemoveLinkPartner/.test(t)) return L.removeLink;
  if (/SetGroupId|set_group/i.test(t)) return L.setGroup;
  if (/RemoveGroupId/.test(t)) return L.removeGroup;
  if (/ConfigTemperatures/.test(t)) return L.tempConfig;
  if (/WakeUp/.test(t)) return L.wake;
  return t;
}

const STATE_ICONS = {
  queued: "mdi:timer-sand",
  waiting_credit: "mdi:radio-tower",
  sending: "mdi:access-point",
  waiting_ack: "mdi:check-network-outline",
};

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

class CulMaxQueueCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = "";
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    const langChanged = this._hass && qLang(this._hass) !== qLang(hass);
    this._hass = hass;
    if (first) this._subscribe();
    else if (langChanged) this._render();
  }

  get _t() {
    return qText(qLang(this._hass));
  }

  get _locale() {
    const language = this._hass?.locale?.language || this._hass?.language || "en";
    return language === "en" ? "en-GB" : language;
  }

  _describe(text) {
    return describe(text, qLang(this._hass), this._locale);
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
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
          this._render();
        },
        { type: "cul_max/queue/subscribe" }
      )
      .catch((err) => {
        this._error = err?.message || this._t.unavailable;
        this._unsub = null;
        this._render();
      });
  }

  async _cancel(entryId, commandId) {
    try {
      await this._hass.callWS({ type: "cul_max/queue/cancel", entry_id: entryId, command_id: commandId });
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    }
  }

  async _clearDevice(entryId, address, name) {
    if (!window.confirm(this._t.confirmClear(name))) return;
    try {
      await this._hass.callWS({ type: "cul_max/queue/clear_device", entry_id: entryId, address });
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    }
  }

  _gatewayHtml(gw, multi) {
    const T = this._t;
    const credit = gw.credit || {};
    const pct = credit.credit_max ? Math.min(100, (100 * (credit.credit_10ms || 0)) / credit.credit_max) : 0;
    const busy = gw.commands.length || gw.pending_config.length;
    const eta = busy
      ? gw.estimated_seconds > 5
        ? T.doneIn(fmtDuration(gw.estimated_seconds))
        : T.sendingSoon
      : T.nothing;
    const rows = gw.commands
      .map((cmd) => {
        const icon = STATE_ICONS[cmd.state] || "mdi:help";
        const label = T.states[cmd.state] || cmd.state;
        const attempt =
          cmd.attempt > 1 || cmd.state === "waiting_ack" ? ` · ${T.attempt(cmd.attempt, cmd.max_attempts)}` : "";
        return `<div class="row ${cmd.state}">
            <ha-icon icon="${icon}"></ha-icon>
            <div class="main">
              <div class="what">${qEsc(cmd.device_name || "CUL")}: ${qEsc(this._describe(cmd.description))}</div>
              <div class="sub">${qEsc(label)}${attempt} · ${qEsc(T.priorities[cmd.priority] || cmd.priority)} · ${T.since(
          fmtDuration(cmd.waiting_seconds)
        )}${cmd.superseded ? ` · ${T.superseded}` : ""}</div>
            </div>
            <button class="x" title="${qEsc(T.removeCmd)}" data-entry="${qEsc(gw.entry_id)}" data-cancel="${cmd.id}">
              <ha-icon icon="mdi:close"></ha-icon></button>
          </div>`;
      })
      .join("");
    const pending = gw.pending_config
      .map((p) => {
        const next = p.next_attempt_at ? new Date(p.next_attempt_at) : null;
        const when =
          next && next > new Date()
            ? ` · ${T.nextAttempt(next.toLocaleTimeString(this._locale, { hour: "2-digit", minute: "2-digit" }))}`
            : "";
        return `<div class="row pending">
            <ha-icon icon="mdi:upload-network-outline"></ha-icon>
            <div class="main">
              <div class="what">${qEsc(p.device_name)}: ${qEsc(T.packets(p.count))}</div>
              <div class="sub">${qEsc(T.next(this._describe(p.next)))}${p.attempts ? ` · ${T.attempts(p.attempts)}` : ""}${when}${
          p.last_error ? ` · ${qEsc(p.last_error)}` : ""
        }</div>
            </div>
            <button class="x" title="${qEsc(T.discardPending)}" data-entry="${qEsc(gw.entry_id)}"
              data-clear="${qEsc(p.device)}" data-name="${qEsc(p.device_name)}"><ha-icon icon="mdi:delete-outline"></ha-icon></button>
          </div>`;
      })
      .join("");
    return `
      <div class="gw">
        ${multi ? `<div class="gwname">${qEsc(gw.gateway)}${gw.connected ? "" : ` – ${T.notConnected}`}</div>` : ""}
        <div class="budget">
          <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
          <div class="btext">
            <span>${T.budget} ${Math.round(credit.credit_10ms || 0)} / ${Math.round(credit.credit_max || 0)}
              · +${credit.recovery_per_second ?? "?"}/s</span>
            <span class="${busy ? "busy" : "idle"}">${qEsc(eta)}</span>
          </div>
        </div>
        ${
          busy
            ? `<div class="list">${rows}${pending}</div>`
            : `<div class="empty"><ha-icon icon="mdi:check-circle-outline"></ha-icon>${T.allSent}</div>`
        }
      </div>`;
  }

  _render() {
    if (!this._config) return;
    const T = this._t;
    const gateways = this._data?.gateways || [];
    const body = this._error
      ? `<div class="msg">${qEsc(this._error)}</div>`
      : !this._data
        ? `<div class="msg">${T.loading}</div>`
        : gateways.map((gw) => this._gatewayHtml(gw, gateways.length > 1)).join("");
    this.shadowRoot.innerHTML = `${this._style()}
      <ha-card>
        <div class="wrapper">
          <div class="header"><ha-icon icon="mdi:radio-tower"></ha-icon><div class="title">${qEsc(
            // the old default title was stored in the card config: translate it too
            !this._config.title || this._config.title === Q_TEXT.de.title ? T.title : this._config.title
          )}</div></div>
          ${body}
          <div class="hint">${T.hint}</div>
        </div>
      </ha-card>`;
    this.shadowRoot.querySelectorAll("[data-cancel]").forEach((btn) =>
      btn.addEventListener("click", () => this._cancel(btn.dataset.entry, Number(btn.dataset.cancel)))
    );
    this.shadowRoot.querySelectorAll("[data-clear]").forEach((btn) =>
      btn.addEventListener("click", () => this._clearDevice(btn.dataset.entry, btn.dataset.clear, btn.dataset.name))
    );
  }

  _style() {
    return `<style>
      :host { display: block; }
      .wrapper { padding: 16px; }
      .header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
      .header ha-icon { color: var(--secondary-text-color); }
      .title { font-size: 1.1rem; font-weight: 600; }
      .msg { padding: 8px 0; color: var(--secondary-text-color); }
      .gw + .gw { margin-top: 16px; }
      .gwname { font-weight: 600; margin-bottom: 6px; }
      .bar { height: 8px; border-radius: 4px; background: var(--secondary-background-color); overflow: hidden; }
      .fill { height: 100%; background: var(--primary-color); transition: width 0.5s; }
      .btext { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; margin-top: 4px;
        font-size: 0.82rem; color: var(--secondary-text-color); }
      .btext .busy { color: var(--primary-color); font-weight: 600; }
      .list { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
      .row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 10px;
        background: var(--secondary-background-color); }
      .row ha-icon { --mdc-icon-size: 20px; color: var(--secondary-text-color); flex: none; }
      .row.sending ha-icon, .row.waiting_ack ha-icon { color: var(--primary-color); }
      .main { flex: 1; min-width: 0; }
      .what { font-size: 0.92rem; overflow-wrap: anywhere; }
      .sub { font-size: 0.78rem; color: var(--secondary-text-color); margin-top: 2px; }
      .x { border: none; background: none; cursor: pointer; color: var(--secondary-text-color); padding: 4px;
        border-radius: 50%; display: inline-flex; }
      .x:hover { background: rgba(var(--rgb-primary-text-color, 0, 0, 0), 0.08); }
      .x ha-icon { --mdc-icon-size: 18px; }
      .empty { display: flex; align-items: center; gap: 8px; margin-top: 10px; color: var(--secondary-text-color); }
      .empty ha-icon { color: var(--success-color, #43a047); }
      .hint { margin-top: 12px; font-size: 0.78rem; color: var(--secondary-text-color); }
    </style>`;
  }
}

if (!customElements.get("cul-max-queue-card")) {
  customElements.define("cul-max-queue-card", CulMaxQueueCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-queue-card")) {
  window.customCards.push({
    type: "cul-max-queue-card",
    name: "CUL MAX radio queue",
    description: "What is waiting for radio time: send budget, remaining time, commands and pending configuration",
    preview: false,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}

if (typeof module !== "undefined") {
  module.exports = { describe };
}
