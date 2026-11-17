// Suppliers shown OUTSIDE the Daisycon tool, in our own design.
//
// Fill this list from your own sources (supplier tariff sheets, direct
// affiliate programmes). Do NOT copy data out of the Daisycon widget here —
// the widget terms forbid using its material outside the tool.
//
// order     lower number = higher on the page
// example   true shows a "Voorbeeld" badge; remove once the data is real
// prices    incl. VAT; leave null to hide a row
window.WB4Y_OWN_SUPPLIERS = [
  {
    order: 1,
    example: true,
    name: "Voorbeeld Energie",
    contract: "1 jaar vast",
    tags: ["Vaste tarieven", "Groene stroom uit NL"],
    cashback: 150,
    electricityPerKwh: 0.299,
    gasPerM3: 1.62,
    url: "https://example.com/aanmelden?ref=wb4y",
    updated: "2026-11-17",
  },
  {
    order: 2,
    example: true,
    name: "Voorbeeld Coöperatie",
    contract: "Variabel",
    tags: ["Variabele tarieven", "Maandelijks opzegbaar"],
    cashback: null,
    electricityPerKwh: 0.315,
    gasPerM3: 1.69,
    url: "https://example.com/coop?ref=wb4y",
    updated: "2026-11-17",
  },
];
