# Onderzoek voorwaarden energieleveranciers

**Datum:** 17 november 2026
**Doel:** bepalen bij welke leveranciers we tarieven automatisch mogen ophalen (zie `supplier_tariffs.py`) en welke handmatig blijven.

Dit is geen juridisch advies. Opnieuw controleren bij elke nieuwe leverancier en minstens één keer per jaar.

## Uitkomst

| Leverancier | Automatisch? | Reden | Bron |
|---|---|---|---|
| SamenOM | ✅ ja (openbare pagina) | Geen verbod gevonden | [samenom.nl/voorwaarden](https://www.samenom.nl/voorwaarden/) |
| PowerPeers | ✅ ja (aanmeldflow) | Geen websitevoorwaarden gevonden, alleen contractvoorwaarden en privacy | [powerpeers.nl/voorwaarden](https://powerpeers.nl/voorwaarden/) |
| Pure Energie | ✅ ja (aanmeldflow) | Geen verbod gevonden | [pure-energie.nl/voorwaarden](https://pure-energie.nl/voorwaarden/) |
| Budget Thuis | ❌ handmatig | Disclaimer verbiedt hergebruik; robots.txt blokkeert de aanbodflow | [budgetthuis.nl/disclaimer](https://www.budgetthuis.nl/disclaimer) |
| Eneco | ❌ handmatig | Disclaimer verbiedt reproduceren/gebruiken | [eneco.nl/disclaimer](https://www.eneco.nl/disclaimer/) |
| Oxxio | ❌ handmatig | Disclaimer verbiedt reproduceren/gebruiken | [oxxio.nl/klantenservice/disclaimer](https://www.oxxio.nl/klantenservice/disclaimer) |
| Vandebron | ❌ handmatig | Voorwaarden verbieden reproduceren/gebruiken | [vandebron.nl/voorwaarden](https://vandebron.nl/voorwaarden) |
| Greenchoice | ❌ handmatig | Disclaimer verbiedt opslaan in geautomatiseerd gegevensbestand | [greenchoice.nl/disclaimer](https://www.greenchoice.nl/disclaimer/) |
| Energiek | ❌ handmatig | Gebruiksvoorwaarden art. 8 verbieden hergebruik van gegevens | [energiek.nl/disclaimer](https://www.energiek.nl/disclaimer) |
| Vattenfall | ❌ handmatig | Voorwaarden verbieden kopiëren; Vattenfall deelt prijzen alleen via de Daisycon-vergelijker | [vattenfall.nl/voorwaarden](https://www.vattenfall.nl/voorwaarden/) |
| UnitedConsumers | ❌ handmatig | Disclaimer verbiedt elektronisch kopiëren | [unitedconsumers.com/…/disclaimer](https://www.unitedconsumers.com/over-ons/service-en-contact/disclaimer) |
| Essent | ❌ handmatig | Blokkeert automatische browsers (403) | – |
| Energiedirect | ❌ handmatig | Blokkeert automatische browsers (403) | – |

## Relevante passages

**Budget Thuis** (disclaimer, kop "Copyright")
> Niets van deze websites mag zonder schriftelijke en voorafgaande toestemming van Budget Thuis worden gereproduceerd of gebruikt, anders dan het downloaden, en het bekijken daarvan op een enkele computer en/of het printen van een enkele hardcopy ten behoeve van persoonlijk, niet bedrijfsmatig gebruik.

robots.txt: `Disallow: /api/`, `Disallow: /*aanbod-op-maat`, `Disallow: /*?*`

**Eneco** (disclaimer)
> Niets van deze website mag zonder schriftelijke en voorafgaande toestemming van Eneco worden gereproduceerd of gebruikt, anders dan het downloaden, en het bekijken daarvan op een enkele computer en/of het printen van een enkele hardcopy ten behoeve van persoonlijk, niet bedrijfsmatig gebruik.

**Oxxio** (disclaimer): dezelfde tekst als Eneco, met "Oxxio".

**Vandebron** (voorwaarden, kop "Copyright")
> Alle rechten waaronder alle intellectuele eigendomsrechten op alle inhoudelijke informatie en het beeldmateriaal op de website blijven te allen tijde voorbehouden aan Vandebron dan wel haar licentiegevers. Niets van deze website mag zonder schriftelijke en voorafgaande toestemming van Vandebron worden gereproduceerd of gebruikt, anders dan het downloaden, en het bekijken daarvan op een enkele computer en/of het printen van een enkele hardcopy ten behoeve van persoonlijk, niet bedrijfsmatig gebruik.

**Greenchoice** (disclaimer)
> Niets uit de inhoud van deze site mag worden verveelvoudigd, opgeslagen in een geautomatiseerd gegevensbestand, of openbaar gemaakt, in enige vorm of op enige wijze, hetzij elektronisch, mechanisch, door fotokopieën, opname of enig andere manier, zonder voorafgaande schriftelijke toestemming van Greenchoice.

**Energiek** (gebruiksvoorwaarden, art. 8 Intellectuele eigendom, versie 1 juli 2024)
> Elke reproductie, publieke mededeling of hergebruik van de Websites of Applicaties of een deel daarvan, d.i. met inbegrip van - doch niet beperkt tot - de daarin vervatte tekst, afbeeldingen, codes, interface elementen, informatie, gegevens, videobestanden en geluidsbestanden, op welke wijze dan ook, is verboden behoudens na uitdrukkelijke, schriftelijke en voorafgaande toestemming van Energiek.

**Vattenfall** (voorwaarden, kop "Intellectuele eigendomsrechten")
> Het is niet toegestaan het materiaal op deze website/internetdiensten te kopiëren, te verveelvoudigen, door te sturen, te verspreiden, openbaar te maken of tegen vergoeding beschikbaar te stellen aan derden, zonder onze uitdrukkelijke toestemming.

robots.txt: `Disallow: /*?`

**UnitedConsumers** (disclaimer en copyright)
> De inhoud van deze website wordt beschermd door het auteursrecht. Deze mag niet elektronisch of anderszins worden gekopieerd, gereproduceerd of in enige vorm worden gedistribueerd zonder schriftelijke toestemming van UnitedConsumers. Als kopiëren, reproduceren of distributie noodzakelijk is om deze website op een efficiënte manier via het internet te raadplegen en gebruik te maken van de daarop aangeboden diensten, geldt bovenstaande niet.

**Essent en Energiedirect.** Een automatische browser krijgt een CloudFront-foutmelding: *"403 ERROR – The request could not be satisfied. Request blocked."* Dat gebeurde op de aanmeldflow en op openbare pagina's (`essent.nl/energie/energieprijzen`, `energiedirect.nl/klantenservice/contract/tarieven`). Hun websitevoorwaarden zijn niet verder onderzocht, omdat de blokkade al duidelijk is.

## Correspondentie

**Daisycon (Kristian), energie-API**
> In terms of the energy API, I have to unfortunately inform you that this is being phased out currently so we are not accepting any new users for the API.

Op de vraag naar een andere manier om tarieven te krijgen: *"not on Daisycon at this point unfortunately."*

**Vattenfall (Rob), via het Daisycon-supportportaal**
> For this we provide the contract en price details to the Daisycon price comparison. There is no other way we share our daily prices.

**Daisycon-widgetvoorwaarden** (relevant voor het gebruik van vergelijkerdata in een eigen ontwerp)
> You will place the code of the tool on your website as offered by Daisycon and you will not make any changes to the content yourself, unless otherwise agreed upon after prior consent. Appearance adjustments, for example by using an alternative CSS, are allowed.
>
> You will not copy or use the material provided in the tool in any way other than for which the tool was originally intended.

De widget restylen met eigen CSS mag. De data in een eigen vergelijker tonen mag alleen met voorafgaande toestemming van Daisycon.

## robots.txt van de onderzochte sites

| Site | Relevante regels voor `User-agent: *` |
|---|---|
| budgetthuis.nl | `/api/`, `/*aanbod-op-maat`, `/*persoonlijk-aanbod`, `/*?*` geblokkeerd |
| vattenfall.nl | `/*?` geblokkeerd (alle URL's met querystring) |
| nextenergy.nl | `/bereken-je-aanbod` geblokkeerd |
| engie.nl | `/*?klant-type=`, `/*?srule=`, `/zoeken/?q=` geblokkeerd |
| powerpeers.nl | alleen `/vrienden/` geblokkeerd |
| samenom.nl | `/voorwaarden/`, `/faqs/*`, `/projecten/*` geblokkeerd; `/tarieven/` toegestaan |
| pure-energie.nl, eneco.nl, oxxio.nl, essent.nl, energiedirect.nl, greenchoice.nl, energiek.nl, vandebron.nl, unitedconsumers.com | geen regels die de tarief- of aanmeldpagina's raken |

## Methode en beperkingen

- De juridische pagina's zijn gevonden via de footerlinks op de homepage, en anders via veelgebruikte adressen (`/disclaimer`, `/voorwaarden`).
- Gezocht is op o.a. *scrapen, geautomatiseerd, robot, crawl, verveelvoudigen, reproduceren, openbaar maken, databank, bedrijfsmatig, hergebruik, kopiëren, intellectuele eigendom, auteursrecht*. Treffers zijn gelezen en geciteerd.
- **Geen verbod gevonden is niet hetzelfde als toestemming.** Bij PowerPeers zijn helemaal geen websitevoorwaarden gevonden.
- De algemene leveringsvoorwaarden (pdf's voor klanten) zijn niet gelezen. Die gelden voor energiecontracten, niet voor het gebruik van de website.
- Of zulke disclaimers juridisch bindend zijn als je ze nooit hebt geaccepteerd, is onzeker. Een prijs is als feit niet auteursrechtelijk beschermd. Wij volgen de voorwaarden toch, omdat het om affiliatepartners gaat.

## Vervolg

- Affiliatemanagers mailen om toestemming te vragen (versie A voor handmatig, versie B voor automatisch). Bij een "ja" de leverancier toevoegen aan `supplier_tariffs.py` en deze tabel bijwerken.
- Daisycon om toestemming vragen om de vergelijkerdata in een eigen ontwerp te tonen, met verwijzing naar het antwoord van Vattenfall.
