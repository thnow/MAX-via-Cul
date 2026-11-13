# Translating MAX! via CUL

The integration is complete in **English** and **German**. Adding another
language takes two kinds of files – no Python or JavaScript knowledge needed
beyond copying a block and replacing the texts.

## Where the texts are

| What | File | Which language is shown |
|---|---|---|
| Entity names, services, setup dialog, error messages | `custom_components/cul_max/translations/<lang>.json` | names: the **server language** of Home Assistant (*Settings → System → General*); error messages: the **profile language** of the user |
| Dashboard cards | the `*_TEXT` block at the top of each file in `custom_components/cul_max/frontend/` | the **profile language** of the user |
| Topology picture | `TOPOLOGY_TEXT` in `custom_components/cul_max/topology.py` | the **server language** |

Anything you do not translate falls back to English, so a partial
translation already works.

## 1. Home Assistant texts

1. Copy `custom_components/cul_max/translations/en.json` to
   `translations/<lang>.json`, e.g. `pl.json` (use the language code Home
   Assistant uses).
2. Translate the **values** only. Keep keys, the JSON structure and
   placeholders such as `{address}` or `{day}` exactly as they are.
3. Leave out what you do not want to translate; Home Assistant uses English
   for missing entries.
4. Do not put placeholders in single quotes (`'{day}'`); use `"{day}"` or no
   quotes – Home Assistant's validation rejects the single-quoted form.

## 2. Dashboard cards

Each card has one text table near the top:

| Card | File | Table(s) |
|---|---|---|
| Week program | `cul-max-week-profile-card.js` | `W_TEXT`, `DAY_NAMES`, `MODE_NAMES` |
| Vacation / summer mode | `cul-max-vacation-card.js` | `V_TEXT` |
| Radio queue | `cul-max-queue-card.js` | `Q_TEXT` |
| Pairing | `cul-max-pairing-card.js` | `P_TEXT` |
| Topology | `cul-max-topology-card.js` | `T_TEXT` |

Add a block for your language next to `de` and `en`, e.g.:

```js
const Q_TEXT = {
  de: { ... },
  en: { ... },
  pl: {
    title: "Kolejka radiowa",
    doneIn: (d) => `gotowe za ok. ${d}`,
    // ...
  },
};
```

- Copy the `en` block and translate it. Entries you leave out are shown in
  English.
- Some entries are small functions such as ``(d) => `done in about ${d}` ``.
  Keep the part before `=>` unchanged and translate only the text; the
  `${...}` parts are filled in by the card.
- `DAY_NAMES` needs short and long names for all seven days.
- Numbers, times and dates are formatted by the browser in the user's
  language automatically.

The cards pick the block that matches the profile language (`pl` for
`pl` or `pl-PL`); without a matching block they show English.

## 3. Topology picture

The texts inside the topology picture (states, notes, legend) are in
`TOPOLOGY_TEXT` at the top of `custom_components/cul_max/topology.py`. Add a
block for your language next to `de` and `en` and keep the placeholders such
as `{days}`. The picture is drawn on the server, so it follows the **server
language** of Home Assistant.

## 4. Check your work

From the repository root:

```sh
pip install -r requirements_test.txt
python3 -m pytest custom_components/cul_max/tests/test_translations.py
```

The test checks that your files only contain keys that exist in English,
that placeholders match and that every card text has the same form as the
English one (a text stays a text, a function takes the same values). It needs
[Node.js](https://nodejs.org/) for the card part and skips it otherwise.

To see the cards, copy `custom_components/cul_max` into your Home Assistant,
restart, set your profile language and reload the browser.

## 5. Send it

Open a pull request on GitHub with your files – or, if that is too much
hassle, attach them to an issue. Thank you!
