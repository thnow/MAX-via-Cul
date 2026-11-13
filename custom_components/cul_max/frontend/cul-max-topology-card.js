/*
 * CUL MAX! topology card
 *
 * Shows the topology picture of one or all CULs (image entity of the
 * integration) and opens it in full size in a new browser tab, where it can be
 * zoomed freely. The link is taken from the entity at click time, because the
 * access token in it changes every few minutes.
 */

// UI language: the profile language if this card has texts for it, else
// English (see TRANSLATING.md).
const T_TEXT = {
  de: {
    title: "MAX! Topologie",
    open: "In neuem Tab öffnen",
    openHint: "Volle Größe in neuem Tab öffnen",
    none: "Kein Topologie-Bild der Integration gefunden.",
    unavailable: "Bild gerade nicht verfügbar.",
  },
  en: {
    title: "MAX! topology",
    open: "Open in new tab",
    openHint: "Open in full size in a new tab",
    none: "No topology picture of the integration found.",
    unavailable: "Picture currently unavailable.",
  },
};

const tLang = (hass) => {
  const language = String(hass?.locale?.language || hass?.language || "en").toLowerCase();
  const base = language.split("-")[0];
  return T_TEXT[language] ? language : T_TEXT[base] ? base : "en";
};

const tEsc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);

class CulMaxTopologyCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._key = "";
  }

  get _t() {
    const lang = tLang(this._hass);
    return { ...T_TEXT.en, ...(T_TEXT[lang] || {}) };
  }

  setConfig(config) {
    this._config = { ...(config || {}) };
    this._key = "";
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  /** Configured entity, or all topology pictures of the integration. */
  _entities() {
    if (this._config?.entity) return [this._config.entity];
    const registry = this._hass?.entities || {};
    return Object.keys(this._hass?.states || {})
      .filter((id) => id.startsWith("image.") && registry[id]?.platform === "cul_max")
      .sort();
  }

  _picture(entityId) {
    const state = this._hass?.states?.[entityId];
    if (!state || state.state === "unavailable") return "";
    return state.attributes?.entity_picture || "";
  }

  _open(entityId) {
    const url = this._picture(entityId);
    if (url) window.open(url, "_blank", "noopener");
  }

  _render() {
    if (!this._hass || !this._config) return;
    const t = this._t;
    const entities = this._entities();
    const items = entities.map((id) => ({
      id,
      name: entities.length > 1 ? this._hass.states[id]?.attributes?.friendly_name || id : "",
      url: this._picture(id),
    }));
    // re-render only when something visible changed (the token rotates)
    const key = JSON.stringify([tLang(this._hass), this._config, items]);
    if (key === this._key) return;
    this._key = key;
    const title = this._config.title ?? t.title;
    const body = items.length
      ? items
          .map(
            (item) => `
        <div class="item">
          ${item.name ? `<div class="name">${tEsc(item.name)}</div>` : ""}
          ${
            item.url
              ? `<button class="pic" data-entity="${tEsc(item.id)}" title="${tEsc(t.openHint)}">
                   <img src="${tEsc(item.url)}" alt="${tEsc(title)}">
                 </button>
                 <div class="actions">
                   <button class="open" data-entity="${tEsc(item.id)}">
                     <ha-icon icon="mdi:open-in-new"></ha-icon><span>${tEsc(t.open)}</span>
                   </button>
                 </div>`
              : `<div class="empty">${tEsc(t.unavailable)}</div>`
          }
        </div>`
          )
          .join("")
      : `<div class="empty">${tEsc(t.none)}</div>`;
    this.shadowRoot.innerHTML = `
      ${this._style()}
      <ha-card>
        ${title ? `<div class="header"><ha-icon icon="mdi:graph-outline"></ha-icon><span>${tEsc(title)}</span></div>` : ""}
        <div class="content">${body}</div>
      </ha-card>`;
    this.shadowRoot.querySelectorAll("[data-entity]").forEach((el) =>
      el.addEventListener("click", () => this._open(el.dataset.entity))
    );
  }

  _style() {
    return `<style>
      ha-card { overflow: hidden; }
      .header { display: flex; align-items: center; gap: 10px; padding: 16px 16px 4px; font-size: 1.15em; font-weight: 600; }
      .header ha-icon { color: var(--state-icon-color, var(--secondary-text-color)); }
      .content { padding: 8px 16px 12px; display: grid; gap: 14px; }
      .name { font-weight: 600; margin-bottom: 6px; }
      .pic { display: block; width: 100%; padding: 0; border: 1px solid var(--divider-color); border-radius: 8px;
        overflow: hidden; background: #f6f8fa; cursor: zoom-in; }
      .pic img { display: block; width: 100%; height: auto; }
      .actions { display: flex; justify-content: flex-end; margin-top: 6px; }
      .open { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px; border: none;
        border-radius: 18px; cursor: pointer; font: inherit; font-weight: 600; background: transparent;
        color: var(--primary-color); }
      .open ha-icon { --mdc-icon-size: 18px; }
      .empty { color: var(--secondary-text-color); padding: 8px 0; }
    </style>`;
  }
}

if (!customElements.get("cul-max-topology-card")) {
  customElements.define("cul-max-topology-card", CulMaxTopologyCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "cul-max-topology-card")) {
  window.customCards.push({
    type: "cul-max-topology-card",
    name: "CUL MAX topology",
    description: "Topology picture of the MAX! installation, opens in full size in a new tab",
    preview: false,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}
