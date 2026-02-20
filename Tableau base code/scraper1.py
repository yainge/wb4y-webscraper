from tableauscraper import TableauScraper as TS

url = "https://public.tableau.com/views/MonitorConsumentenmarktEnergie/Variabeleenvastecontracten?:showVizHome=no"

ts = TS()
ts.loads(url)
wb = ts.getWorkbook()

# Check sheets
print(wb.getWorksheets())

# Try the two relevant ones you found
for name in ["Retail Tarieven staafdiagram", "Retail Tarieven staafdiagram alle contracten"]:
    ws = wb.getWorksheet(name)
    df = ws.data
    print("\n=== ", name, " ===")
    print(df.columns)
    print(df.head())
    df.to_csv(f"{name}.csv", index=False)