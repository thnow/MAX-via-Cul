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

const MAX_DAYS = ["Sa", "So", "Mo", "Di", "Mi", "Do", "Fr"];

const qTemp = (value) =>
  `${Number(value).toLocaleString("de-DE", { minimumFractionDigits: 0, maximumFractionDigits: 1 })} °C`;

/** Technical command description → short German text. */
function describe(text) {
  const t = String(text || "");
  let m;
  if ((m = /ConfigWeekProfile \S+ day=(\d) part=(\d)/.exec(t))) {
    return `Wochenprogramm ${MAX_DAYS[Number(m[1])] || m[1]} (Teil ${Number(m[2]) + 1})`;
  }
  if ((m = /SetTemperature (\d+(?:\.\d+)?) mode=(\w+)(?: until=([\d-]+ [\d:]+))?/.exec(t))) {
    const temp = Number(m[1]);
    if (m[2] === "auto") return temp > 0 ? `Temperatur ${qTemp(temp)} (bis zum nächsten Schaltpunkt)` : "Zurück zum Wochenprogramm";
    if (m[2] === "vacation") return `Urlaub ${qTemp(temp)}${m[3] ? ` bis ${m[3]}` : ""}`;
    if (m[2] === "boost") return "Boost";
    return `Temperatur ${qTemp(temp)} (manuell)`;
  }
  if (/^SetTemperature/.test(t)) return "Temperatur";
  if ((m = /Ist (\d+(?:\.\d+)?) \(extern\), Soll (\d+(?:\.\d+)?)/.exec(t))) {
    return `Raumfühler ${qTemp(m[1])} (Soll ${qTemp(m[2])})`;
  }
  if ((m = /VirtualShutterContactState (open|closed)/.exec(t))) {
    return `Virtueller Fensterkontakt: ${m[1] === "open" ? "offen" : "geschlossen"}`;
  }
  if (/TimeInformation/.test(t)) return "Uhrzeit stellen";
  if (/AddLinkPartner/.test(t)) return "Verknüpfung anlegen";
  if (/RemoveLinkPartner/.test(t)) return "Verknüpfung entfernen";
  if (/SetGroupId|set_group/i.test(t)) return "Gruppe setzen";
  if (/RemoveGroupId/.test(t)) return "Gruppe entfernen";
  if (/ConfigTemperatures/.test(t)) return "Temperatur-Einstellungen";
  if (/WakeUp/.test(t)) return "Wecken";
  return t;
}

const STATE_LABELS = {
  queued: ["mdi:timer-sand", "wartet"],
  waiting_credit: ["mdi:radio-tower", "wartet auf Sendezeit"],
  sending: ["mdi:access-point", "wird gesendet"],
  waiting_ack: ["mdi:check-network-outline", "wartet auf Bestätigung"],
};

const PRIORITY_LABELS = { interactive: "Bedienung", user: "Einstellung", background: "Hintergrund" };

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

class CulMaxQueueCard extends HTMLElement {
  static getStubConfig() {
    return { title: "Funk-Warteschlange" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = "";
  }

  setConfig(config) {
    this._config = { title: "Funk-Warteschlange", ...(config || {}) };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
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
        this._error = err?.message || "Warteschlange nicht verfügbar (Integration ab 0.6.2 nötig)";
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
    if (!window.confirm(`Alles, was für „${name}“ noch wartet, verwerfen?`)) return;
    try {
      await this._hass.callWS({ type: "cul_max/queue/clear_device", entry_id: entryId, address });
    } catch (err) {
      this._error = err?.message || String(err);
      this._render();
    }
  }

  _gatewayHtml(gw, multi) {
    const credit = gw.credit || {};
    const pct = credit.credit_max ? Math.min(100, (100 * (credit.credit_10ms || 0)) / credit.credit_max) : 0;
    const busy = gw.commands.length || gw.pending_config.length;
    const eta = busy
      ? gw.estimated_seconds > 5
        ? `fertig in etwa ${fmtDuration(gw.estimated_seconds)}`
        : "wird gleich gesendet"
      : "nichts zu senden";
    const rows = gw.commands
      .map((cmd) => {
        const [icon, label] = STATE_LABELS[cmd.state] || ["mdi:help", cmd.state];
        const attempt =
          cmd.attempt > 1 || cmd.state === "waiting_ack" ? ` · Versuch ${cmd.attempt}/${cmd.max_attempts}` : "";
        return `<div class="row ${cmd.state}">
            <ha-icon icon="${icon}"></ha-icon>
            <div class="main">
              <div class="what">${qEsc(cmd.device_name || "CUL")}: ${qEsc(describe(cmd.description))}</div>
              <div class="sub">${qEsc(label)}${attempt} · ${qEsc(PRIORITY_LABELS[cmd.priority] || cmd.priority)} · seit ${fmtDuration(
          cmd.waiting_seconds
        )}${cmd.superseded ? " · wird ersetzt" : ""}</div>
            </div>
            <button class="x" title="Aus der Warteschlange entfernen" data-entry="${qEsc(gw.entry_id)}" data-cancel="${cmd.id}">
              <ha-icon icon="mdi:close"></ha-icon></button>
          </div>`;
      })
      .join("");
    const pending = gw.pending_config
      .map((p) => {
        const next = p.next_attempt_at ? new Date(p.next_attempt_at) : null;
        const when =
          next && next > new Date()
            ? ` · nächster Versuch ${next.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`
            : "";
        return `<div class="row pending">
            <ha-icon icon="mdi:upload-network-outline"></ha-icon>
            <div class="main">
              <div class="what">${qEsc(p.device_name)}: ${p.count} Paket${p.count === 1 ? "" : "e"} Konfiguration</div>
              <div class="sub">als Nächstes ${qEsc(describe(p.next))}${p.attempts ? ` · ${p.attempts} Versuch(e)` : ""}${when}${
          p.last_error ? ` · ${qEsc(p.last_error)}` : ""
        }</div>
            </div>
            <button class="x" title="Ausstehende Konfiguration verwerfen" data-entry="${qEsc(gw.entry_id)}"
              data-clear="${qEsc(p.device)}" data-name="${qEsc(p.device_name)}"><ha-icon icon="mdi:delete-outline"></ha-icon></button>
          </div>`;
      })
      .join("");
    return `
      <div class="gw">
        ${multi ? `<div class="gwname">${qEsc(gw.gateway)}${gw.connected ? "" : " – nicht verbunden"}</div>` : ""}
        <div class="budget">
          <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
          <div class="btext">
            <span>Sendebudget ${Math.round(credit.credit_10ms || 0)} / ${Math.round(credit.credit_max || 0)}
              · +${credit.recovery_per_second ?? "?"}/s</span>
            <span class="${busy ? "busy" : "idle"}">${qEsc(eta)}</span>
          </div>
        </div>
        ${
          busy
            ? `<div class="list">${rows}${pending}</div>`
            : `<div class="empty"><ha-icon icon="mdi:check-circle-outline"></ha-icon>Alles übertragen</div>`
        }
      </div>`;
  }

  _render() {
    if (!this._config) return;
    const gateways = this._data?.gateways || [];
    const body = this._error
      ? `<div class="msg">${qEsc(this._error)}</div>`
      : !this._data
        ? `<div class="msg">Lade …</div>`
        : gateways.map((gw) => this._gatewayHtml(gw, gateways.length > 1)).join("");
    this.shadowRoot.innerHTML = `${this._style()}
      <ha-card>
        <div class="wrapper">
          <div class="header"><ha-icon icon="mdi:radio-tower"></ha-icon><div class="title">${qEsc(this._config.title)}</div></div>
          ${body}
          <div class="hint">Der CUL darf nur 1 % der Zeit senden (36 s pro Stunde, etwa 1 s pro Paket). Größere Änderungen gehen deshalb nach und nach raus.</div>
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
    name: "CUL MAX Funk-Warteschlange",
    description: "Was gerade auf Sendezeit wartet: Sendebudget, Restzeit, Befehle und ausstehende Konfiguration",
    preview: false,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}

if (typeof module !== "undefined") {
  module.exports = { describe };
}
