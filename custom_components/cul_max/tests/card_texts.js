// Prints the structure of a card's text tables as JSON (used by test_translations.py).
// usage: node card_texts.js <card.js> <TABLE> [<TABLE> ...]
const fs = require("fs");
const vm = require("vm");

const [file, ...tables] = process.argv.slice(2);
const describe = (value) => {
  if (typeof value === "function") return { type: "function", arity: value.length };
  if (Array.isArray(value)) return { type: "array", length: value.length };
  if (value && typeof value === "object") {
    return { type: "object", keys: Object.fromEntries(Object.entries(value).map(([k, v]) => [k, describe(v)])) };
  }
  return { type: typeof value };
};
const source = `${fs.readFileSync(file, "utf8")}\n;globalThis.__tables = { ${tables.join(", ")} };`;
const context = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: () => {} },
  window: { customCards: [], setInterval: () => 0, clearInterval: () => {} },
  document: { createElement: () => ({}) },
  console,
  Intl,
  Date,
  setTimeout,
  clearTimeout,
};
vm.createContext(context);
vm.runInContext(source, context, { filename: file });
const out = {};
for (const [name, table] of Object.entries(context.__tables)) {
  out[name] = Object.fromEntries(Object.entries(table).map(([lang, texts]) => [lang, describe(texts)]));
}
process.stdout.write(JSON.stringify(out));
