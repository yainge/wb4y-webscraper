// Watt's Best for You — comparison page setup.
//
// WIDGET: order and selection are controlled through the widget's own config
// options (what the Daisycon configurator sets). We don't reorder or inject
// cards inside the widget: the terms forbid changing its content.
//
// OWN SUPPLIERS: rendered from own-suppliers.js in our own design, as a
// separate section next to the widget.

const WB4Y = {
  mediaId: 415069,

  widget: {
    // Default sort: "price" (Laagste prijs) or "discount" (Hoogste korting).
    // The widget only supports these two, and only via the ?sort= URL param.
    sort: "price",

    // Which Daisycon suppliers to show. Empty = all. Daisycon provider ids:
    // 1 Vattenfall, 4 Engie, 6 Energiedirect, 7 NLE, 8 Oxxio, 9 Eneco,
    // 10 Essent, 17 Pure Energie, 18 Budget Energie, 28 Vandebron,
    // 33 PowerPeers, 61 Frank Energie, 63 NextEnergy, 64 Tibber
    providerIds: [],

    // Contract types: "fixed", "variable", "dynamic"
    tariffTypes: ["fixed"],
    // Fixed durations in months: 12 and/or 36 (empty = both)
    durations: [],

    household: 2,
    buttonText: "Bekijk aanbod",
  },

  // Where our own suppliers appear relative to the widget: "before" | "after"
  ownSuppliersPosition: "after",
};

function buildWidget(container) {
  const w = WB4Y.widget;

  // Same "filter" format the Daisycon configurator generates.
  const filter = {
    tariffType: { value: w.tariffTypes },
    duration: { value: w.durations },
    providerId: { value: w.providerIds },
    household: { value: [w.household] },
  };

  // Default sort is read from the page URL; don't override a visitor's choice.
  const url = new URL(location.href);
  if (w.sort !== "price" && !url.searchParams.has("sort")) {
    url.searchParams.set("sort", w.sort);
    history.replaceState(null, "", url);
  }

  const el = document.createElement("div");
  el.className = "dc-tool dc-energy-tool";
  el.dataset.config = JSON.stringify({
    mediaId: WB4Y.mediaId,
    locale: "nl-NL",
    buttonText: w.buttonText,
    filter,
  });
  container.append(el);

  const s = document.createElement("script");
  s.src = "https://daisycon.tools/energy-nl/app.js";
  document.body.append(s);
}

const euro = (n, digits = 2) =>
  n.toLocaleString("nl-NL", { style: "currency", currency: "EUR", minimumFractionDigits: digits, maximumFractionDigits: digits });

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderOwnSuppliers(container) {
  const list = [...(window.WB4Y_OWN_SUPPLIERS || [])].sort((a, b) => a.order - b.order);
  if (!list.length) { container.hidden = true; return; }

  const ul = el("ul", "own-list");
  for (const s of list) {
    const li = el("li", "own-card");

    const id = el("div");
    id.append(el("p", "own-card__name", s.name), el("p", "own-card__contract", s.contract));

    const rates = el("div", "own-card__rates");
    for (const [val, unit] of [[s.electricityPerKwh, "kWh"], [s.gasPerM3, "m³"]]) {
      if (val == null) continue;
      const p = el("p", "own-card__rate");
      p.append(el("strong", null, euro(val, unit === "kWh" ? 4 : 3)), ` / ${unit}`);
      rates.append(p);
    }

    const tags = el("div", "own-card__tags");
    if (s.example) tags.append(el("span", "tag tag--example", "Voorbeeld"));
    if (s.cashback) tags.append(el("span", "tag tag--cashback", `${euro(s.cashback, 0)} cashback`));
    for (const t of s.tags || []) tags.append(el("span", "tag", t));

    const footer = el("div", "own-card__footer");
    footer.append(el("span", "own-card__updated", s.updated ? `Tarieven van ${new Date(s.updated).toLocaleDateString("nl-NL")}` : ""));
    const a = el("a", "btn", "Bekijk aanbod");
    a.href = s.url;
    a.rel = "sponsored noopener";
    a.target = "_blank";
    footer.append(a);

    li.append(id, rates, tags, footer);
    ul.append(li);
  }
  container.querySelector("[data-own-list]").append(ul);
}

document.addEventListener("DOMContentLoaded", () => {
  const widgetSection = document.getElementById("vergelijker");
  const ownSection = document.getElementById("andere-leveranciers");
  if (WB4Y.ownSuppliersPosition === "before") widgetSection.before(ownSection);
  renderOwnSuppliers(ownSection);
  buildWidget(widgetSection.querySelector("[data-widget]"));
});
