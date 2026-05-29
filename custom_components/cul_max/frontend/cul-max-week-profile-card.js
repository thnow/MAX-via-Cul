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
      Object.keys(hass?.states || {}).find((entityId) => {
        const state = hass.states[entityId];
        return CulMaxWeekProfileCard._isCulMaxClimate(entityId, state);
      }) || "";
    return {
      entity,
      title: "Wochenprofil",
      show_current_temp: true,
    };
  }

  static getConfigElement() {
    if (customElements.get("cul-max-week-profile-card-editor")) {
      return document.createElement("cul-max-week-profile-card-editor");
    }

    if (!customElements.get("cul-max-week-profile-card-editor-fallback")) {
      customElements.define(
        "cul-max-week-profile-card-editor-fallback",
        class extends HTMLElement {
          setConfig(config) {
            this._config = {
              title: "Wochenprofil",
              show_current_temp: true,
              ...config,
            };
            this.innerHTML = "<div style='padding:8px 0'>Editor wird geladen ...</div>";
          }
        }
      );
    }
    return document.createElement("cul-max-week-profile-card-editor-fallback");
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Entity required");
    }
    this._config = {
      title: "Wochenprofil",
      show_current_temp: true,
      ...config,
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 5;
  }

  _dayOrder() {
    return [
      ["monday", "Mo"],
      ["tuesday", "Di"],
      ["wednesday", "Mi"],
      ["thursday", "Do"],
      ["friday", "Fr"],
      ["saturday", "Sa"],
      ["sunday", "So"],
    ];
  }

  _parseDayProfile(raw) {
    if (!raw || typeof raw !== "string") {
      return [];
    }
    const tokens = raw.split(",").map((part) => part.trim()).filter(Boolean);
    if (tokens.length === 0) {
      return [];
    }
    const segments = [];
    let currentTemp = tokens[0] ?? "";
    let currentFrom = "00:00";

    for (let idx = 1; idx < tokens.length; idx += 2) {
      const until = tokens[idx];
      const nextTemp = tokens[idx + 1];
      if (!until) {
        break;
      }
      if (until === "00:00" && currentFrom !== "00:00") {
        segments.push({
          from: currentFrom,
          until: "24:00",
          temp: currentTemp,
        });
        return segments;
      }
      if (until === "00:00" && currentFrom === "00:00") {
        continue;
      }
      segments.push({
        from: currentFrom,
        until,
        temp: currentTemp,
      });
      currentFrom = until;
      if (until === "24:00") {
        return segments;
      }
      if (nextTemp !== undefined) {
        currentTemp = nextTemp;
      }
    }

    if (currentFrom !== "24:00") {
      segments.push({
        from: currentFrom,
        until: "24:00",
        temp: currentTemp,
      });
    }
    return segments.filter((segment, index, allSegments) => {
      if (segment.from === segment.until) {
        return false;
      }
      const previous = allSegments[index - 1];
      return !previous
        || previous.temp !== segment.temp
        || previous.until !== segment.until
        || previous.from !== segment.from;
    });
  }

  _render() {
    if (!this._hass || !this._config) {
      return;
    }
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) {
      this.innerHTML = `
        <ha-card>
          <div class="card-content">Entität nicht gefunden: ${this._config.entity}</div>
        </ha-card>
      `;
      return;
    }
    if (!CulMaxWeekProfileCard._isCulMaxClimate(this._config.entity, stateObj)) {
      this.innerHTML = `
        <ha-card>
          <div class="card-content" style="padding:16px">
            <div style="font-weight:600; margin-bottom:8px;">Inkompatible Entität</div>
            <div style="line-height:1.5;">
              Diese Karte funktioniert nur mit <code>cul_max</code>-Climate-Entitäten,
              z.&nbsp;B. <code>climate.wandthermostat_schlafzimmer</code>.
            </div>
            <div style="margin-top:8px; color: var(--secondary-text-color);">
              Gewählt: <code>${this._config.entity}</code>
            </div>
          </div>
        </ha-card>
      `;
      return;
    }

    const attrs = stateObj.attributes || {};
    const rows = this._dayOrder()
      .map(([key, shortLabel]) => {
        const raw = attrs[`week_profile_${key}`];
        const segments = this._parseDayProfile(raw);
        const segmentHtml = segments.length
          ? segments
              .map(
                (segment) => `
                  <span class="segment">
                    <span class="temp">${segment.temp}&thinsp;°C</span>
                    <span class="time">${segment.from}–${segment.until}</span>
                  </span>
                `
              )
              .join("")
          : `<span class="empty">kein Profil</span>`;

        return `
          <div class="row">
            <div class="day">${shortLabel}</div>
            <div class="segments">${segmentHtml}</div>
          </div>
        `;
      })
      .join("");

    const subtitle = [];
    if (attrs.friendly_name) {
      subtitle.push(attrs.friendly_name);
    }
    if (this._config.show_current_temp && attrs.current_temperature != null) {
      subtitle.push(`Ist ${attrs.current_temperature} °C`);
    }
    if (attrs.temperature != null) {
      subtitle.push(`Soll ${attrs.temperature} °C`);
    }

    this.innerHTML = `
      <ha-card>
        <div class="wrapper">
          <div class="header">
            <div>
              <div class="title">${this._config.title}</div>
              <div class="subtitle">${subtitle.join(" • ")}</div>
            </div>
            <div class="badge">${stateObj.state}</div>
          </div>
          <div class="grid">${rows}</div>
        </div>
      </ha-card>
      <style>
        ha-card {
          cursor: pointer;
        }
        .wrapper {
          padding: 16px;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 12px;
          margin-bottom: 14px;
        }
        .title {
          font-size: 1.1rem;
          font-weight: 600;
          line-height: 1.2;
        }
        .subtitle {
          margin-top: 4px;
          color: var(--secondary-text-color);
          font-size: 0.92rem;
        }
        .badge {
          white-space: nowrap;
          border-radius: 999px;
          padding: 4px 10px;
          background: var(--secondary-background-color);
          font-size: 0.85rem;
          color: var(--primary-text-color);
        }
        .grid {
          display: grid;
          gap: 8px;
        }
        .row {
          display: grid;
          grid-template-columns: 38px 1fr;
          gap: 10px;
          align-items: start;
          padding: 8px 0;
          border-top: 1px solid var(--divider-color);
        }
        .row:first-child {
          border-top: 0;
          padding-top: 0;
        }
        .day {
          font-weight: 600;
          color: var(--secondary-text-color);
          padding-top: 3px;
        }
        .segments {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .segment {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 5px 8px;
          border-radius: 10px;
          background: var(--secondary-background-color);
          line-height: 1.2;
        }
        .temp {
          font-weight: 600;
        }
        .time {
          color: var(--secondary-text-color);
          font-size: 0.88rem;
        }
        .empty {
          color: var(--secondary-text-color);
          font-style: italic;
          padding: 6px 0;
        }
      </style>
    `;

    this.querySelector("ha-card")?.addEventListener("click", () => {
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: this._config.entity },
        })
      );
    });
  }
}

if (!customElements.get("cul-max-week-profile-card")) {
  customElements.define("cul-max-week-profile-card", CulMaxWeekProfileCard);
}

class CulMaxWeekProfileCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = {
      title: "Wochenprofil",
      show_current_temp: true,
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _availableEntities() {
    return Object.entries(this._hass?.states || {})
      .filter(([entityId, state]) => CulMaxWeekProfileCard._isCulMaxClimate(entityId, state))
      .map(([entityId, state]) => ({
        entity_id: entityId,
        label: state.attributes.friendly_name || entityId,
      }))
      .sort((a, b) => a.label.localeCompare(b.label, "de"));
  }

  _emitConfig(config) {
    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config },
        bubbles: true,
        composed: true,
      })
    );
  }

  _render() {
    if (!this._config) {
      return;
    }

    const entityOptions = this._availableEntities()
      .map(
        (entry) => `
          <option value="${entry.entity_id}" ${
            entry.entity_id === this._config.entity ? "selected" : ""
          }>${entry.label}</option>
        `
      )
      .join("");

    this.innerHTML = `
      <div class="editor">
        <label>
          <span>Thermostat</span>
          <select data-field="entity">
            <option value="">Bitte waehlen</option>
            ${entityOptions}
          </select>
        </label>
        <label>
          <span>Titel</span>
          <input data-field="title" type="text" value="${this._config.title || ""}" />
        </label>
        <label class="checkbox">
          <input data-field="show_current_temp" type="checkbox" ${
            this._config.show_current_temp ? "checked" : ""
          } />
          <span>Ist-Temperatur anzeigen</span>
        </label>
      </div>
      <style>
        .editor {
          display: grid;
          gap: 12px;
          padding: 8px 0;
        }
        label {
          display: grid;
          gap: 6px;
        }
        label > span {
          color: var(--secondary-text-color);
          font-size: 0.9rem;
        }
        input[type="text"],
        select {
          padding: 8px 10px;
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          font: inherit;
        }
        .checkbox {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .checkbox > span {
          color: var(--primary-text-color);
        }
      </style>
    `;

    const stopEditorEvent = (event) => {
      event.stopPropagation();
    };

    this.querySelector(".editor")?.addEventListener("click", stopEditorEvent);
    this.querySelector(".editor")?.addEventListener("mousedown", stopEditorEvent);
    this.querySelector(".editor")?.addEventListener("mouseup", stopEditorEvent);
    this.querySelector(".editor")?.addEventListener("touchstart", stopEditorEvent);

    this.querySelector('[data-field="entity"]')?.addEventListener("change", (ev) => {
      const value = ev.target.value;
      this._emitConfig({
        ...this._config,
        entity: value,
      });
    });

    this.querySelector('[data-field="title"]')?.addEventListener("input", (ev) => {
      this._emitConfig({
        ...this._config,
        title: ev.target.value,
      });
    });

    this.querySelector('[data-field="show_current_temp"]')?.addEventListener("change", (ev) => {
      this._emitConfig({
        ...this._config,
        show_current_temp: ev.target.checked,
      });
    });
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
    description: "Kompakte Wochenplan-Karte für MAX!-Thermostate",
    preview: true,
    documentationURL: "https://github.com/thnow/MAX-via-Cul/blob/main/README.md",
  });
}
