# Data sources and how each number was verified

This project models the energy an electric car needs on a drive cycle and compares the
result with the official figures. That comparison is only worth something if every input
can be traced to an authoritative source, so this file records where each number comes
from and how it was checked.

Three rules were applied throughout:

1. **Official datasets first.** Regulatory data published by the EU, the US EPA and the UN
   comes before manufacturer brochures; press articles and enthusiast sites were used only
   as leads, never as a source.
2. **No number is taken on trust.** Values are copied programmatically from query results and
   official reports (`tools/build_vehicles.py`, `tools/epa_certification.py`), and every query
   can be re-run. Every other value taken from a document carries a verbatim quote, or the
   spreadsheet cell it was read from, that a script finds in the fingerprinted document, and the
   tests tie the model's regulatory constants to those quotes.
3. **What cannot be verified is not used.** Where a value could not be confirmed from a
   primary source it is listed as open, not estimated.

Data were retrieved on 26 September 2026. The EEA metadata record and table definition
(section 2), the eCFR drive-cycle appendices and the EPA schedule images (section 1), and the
regulation texts first cited in section 4 (Regulation (EU) 2017/1151, 40 CFR 1066.305 and
86.129-00) were retrieved on 27 September 2026.

---

## 1. Drive cycles

| File | Cycle | Primary source | Samples |
|---|---|---|---|
| `data/cycles/wltc_class3b.csv` | WLTC class 3b (Low3 + Medium3-2 + High3-2 + Extra High3) | UN GTR No. 15, ECE/TRANS/180/Add.15 (12 May 2014), Annex 1, Tables A1/7, A1/9, A1/11, A1/12 | 1801 (t = 0..1800 s), km/h |
| `data/cycles/udds.csv` | EPA Urban Dynamometer Driving Schedule (LA-4) | 40 CFR Part 86, Appendix I, paragraph (a) | 1370, mph |
| `data/cycles/hwfet.csv` | EPA Highway Fuel Economy Test | 40 CFR Part 600, Appendix I | 766, mph |

**Verification.** `tools/verify_cycles.py` compares each file second by second with the table
printed in the regulation itself, read from fingerprinted copies: the GTR PDF of section 4, and
the eCFR's point-in-time XML (1 September 2026) of Appendix I to 40 CFR Parts 86 and 600.

| Document | eCFR request | SHA-256 |
|---|---|---|
| 40 CFR 86, Appendix I | <https://www.ecfr.gov/api/versioner/v1/full/2026-09-01/title-40.xml?part=86&appendix=Appendix%20I%20to%20Part%2086> | `47aceb0e68799738952d9df5bc3d71ecec0e84a5afd925bfb8eb9d908d71ccf5` |
| 40 CFR 600, Appendix I | <https://www.ecfr.gov/api/versioner/v1/full/2026-09-01/title-40.xml?part=600&appendix=Appendix%20I%20to%20Part%20600> | `f3cec162e6c700e822804bfda32c737b9d257392bbc86386ccbc4dddd771759a` |

- WLTC: all 1801 speeds identical to Tables A1/7, A1/9, A1/11 and A1/12 of the GTR. The
  machine-readable copy comes from the European Commission JRC reference implementation
  (`JRCSTU/wltp`, `V_class3b.txt`); the file also reproduces that project's phase checksums,
  the sums of the speeds in each phase (11140.3, 17121.2, 25782.2, 29714.9).
- UDDS: all 1370 speeds identical to 40 CFR 86 App. I(a). The CFR table then runs on at rest
  to second 1372, while the EPA file ends at second 1369. Standing still takes no work at the
  wheels, so the difference would only let the car's own consumption run for three more
  seconds.
- HWFET: the 764 speeds of seconds 1 to 764 identical to 40 CFR 600 App. I. At seconds 0 and
  765 the CFR prints the sampling events, "Sample On" and "Sample Off", instead of a speed; the
  file has the car at rest there.

The comparison surfaced four misprinted time labels in the eCFR tables: second 1218 of the UDDS
is printed as "1318", and seconds 466, 636 and 639 of the HWFET as "446", "6.36" and "6.39". In
each case the speed printed next to the label belongs to the corrected second, which is
otherwise missing from the table, and matches the EPA file, so the files are right. The tool
corrects exactly these four labels and fails on any other difference.

`tools/check_cycles.py` repeats what needs nothing but the files: the WLTC phase durations
stated in GTR 15 (Annex 1, para. 3.4: "All low speed phases last 589 seconds (s)", and 433, 455
and 323 s for the medium, high and extra high phases; quoted in `data/reference_values.json`),
the JRC checksums, and the length, distance and average speed the EPA states for its two
cycles, to the digits it prints. The EPA gives them as text drawn on its schedule images, read
here by eye from copies whose fingerprints `tools/verify_cycles.py` checks:

| Cycle | EPA statement | Image, SHA-256 |
|---|---|---|
| UDDS | "Length 1369 seconds - Distance = 7.45 miles - Average Speed = 19.59 mph" | <https://www.epa.gov/sites/default/files/2015-10/uddsdds.gif>, `3a87f73e8ecb4d24ef77fd52b2b4aa6fdaa099886c9561bebdeb0e413124a4a8` |
| HWFET | "Length 765 seconds - Distance = 10.26 miles - Average Speed = 48.3 mph" | <https://www.epa.gov/sites/default/files/2015-10/hwfetdds.gif>, `e6103581acabf959613c79b6f1607f8c6fa600510925332a414457ebe4550a49` |

The script also pins these figures, computed from the verified files, so that any later change
to a file shows up (maximum acceleration as a central difference, `(v[i+1] - v[i-1]) / 2`):

| Phase | Duration (s) | Distance (m) | v_max (km/h) | a_max (m/s²) |
|---|---|---|---|---|
| Low3 | 589 | 3095 | 56.5 | 1.47 |
| Medium3-2 | 433 | 4756 | 76.6 | 1.57 |
| High3-2 | 455 | 7162 | 97.4 | 1.58 |
| Extra High3 | 323 | 8254 | 131.3 | 1.03 |
| **WLTC class 3b** | **1800** | **23266** | 131.3 | |
| UDDS | 1369 | 11 990 (7.45 mi) | 91.25 (56.7 mph) | |
| HWFET | 765 | 16 507 (10.26 mi) | 96.40 (59.9 mph) | |

Stop durations are not reported; the model does not use them.

---

## 2. Vehicles: official EU WLTP values

**Source.** European Environment Agency, *Monitoring of CO2 emissions from passenger cars,
2024 - Final* (Regulation (EU) 2019/631), <https://doi.org/10.2909/5018ec17-2348-4c92-8761-6f2377bbd1c0>,
queried through the public DiscoData SQL service, table
`[CO2Emission].[latest].[co2cars_2024Fv30]`. The EEA's metadata record for the dataset names
that table and gives the licence: "License CC-BY 4.0 [...] Copyright holder:
Directorate-General for Climate Action (DG-CLIMA)" (quotes checked by
`tools/verify_references.py`). Every car registered in the EU is one or more rows. The fields
used here are defined in the EEA's table definition, attached to the same record
(<https://sdi.eea.europa.eu/catalogue/api/records/5018ec17-2348-4c92-8761-6f2377bbd1c0/attachments/Table-definition-cars-2024-Final.xlsx>,
SHA-256 `8c70451bbd47b31f063dcace945fab91fc0f96d0eaed3155cdc450ae6623a3a7`; quotes checked by
the same script):

| Field | Definition in the table definition |
|---|---|
| `M (kg)` | "Mass in running order Completed/complete vehicle" |
| `Mt` | "WLTP test mass" |
| `Z (Wh/km)` | "Electric energy consumption" |
| `Zr` | "Electric range" |
| `R` | "Total new registrations" (the registrations the row stands for) |

**Method.** Under the WLTP interpolation method each car carries its own values, depending
on its options (wheels, packs). `tools/eea_query.py` therefore reports the value set carried
by the most registrations, and the 5th-95th percentile range weighted by registrations,
which covers the option spread and keeps obvious reporting errors out.

| Vehicle | EU variant | Registrations | Mass in running order (kg) | WLTP test mass (kg) | Consumption (Wh/km) | Range (km) |
|---|---|---|---|---|---|---|
| Tesla Model 3 RWD | type 003, variant H6LR | 56,229 | 1836 | 1932 | 132 | 513 |
| Volvo EX30 Single Motor Extended Range | type 2, variant 2ZEL | 40,130 | 1850 | 1920 (1920-1943) | 170 (170-171) | 476 (473-476) |
| Polestar 2 Long Range Single Motor | type V, variant VSFE | 6,323 | 2084 | 2208 (2175-2216) | 152 (150-157) | 641 (616-649) |
| Volkswagen ID.4 Pro (210 kW, RWD) | type E2, variant 4ACEDFAD7PX2, without 4MOTION | 26,250 | 2156 (2149-2156) | 2285 (2253-2324) | 163 (161-171) | 542 (521-562) |

Tesla declares a single WLTP value for the whole variant: 45,736 of the 45,809 complete
records carry the same mass, consumption and range, so there is no spread to report.

**Motor power** comes from the same dataset (`Ep (KW)`, "Engine power"). Member states do not
all report the same value for the same variant, so it is summarised separately, as the value
most registrations carry:

| Vehicle | Motor power (kW) | Share of registrations reporting it |
|---|---|---|
| Tesla Model 3 RWD | 208 | 96.5 % |
| Volvo EX30 Single Motor Extended Range | 200 | 100 % |
| Polestar 2 Long Range Single Motor | 220 | 100 % |
| Volkswagen ID.4 Pro (210 kW, RWD) | 210 | 72.5 % |

For the three cars whose makers publish their power, the EU value matches the manufacturer's
figure exactly (section 6), which supports the Tesla value, although Tesla itself does not
state it on its site.

**What the consumption figure measures.** WLTP electric energy consumption is energy taken
from the mains, so it includes charging losses: "The electric energy consumption EC including
charging losses is defined by the equation" EC = EAC/AER, EAC being "the recharged electric
energy from the mains" and AER the range (GTR 15, Annex 8, para. 4.3.2.2; the equation is
printed as an image, the words are checked by `tools/verify_references.py`). The model computes
energy at the battery; the difference between the two has to be handled explicitly
(section 7).

---

## 3. Vehicles: measured road load (US EPA)

**Source.** US EPA, *Test Car List Data Files*
(<https://www.epa.gov/compliance-and-fuel-economy-data/data-cars-used-testing-fuel-economy>).
For each tested car the file gives the target road-load coefficients of
`F = A + B·v + C·v²`, determined by coastdown on the road and corrected to reference
conditions of **20 °C, 98.21 kPa and no wind** (40 CFR 1066.305, quoted in section 4). Units
are part of the column names.

These are measured, not estimated: they replace the drag coefficient, frontal area and
rolling-resistance coefficient that would otherwise have to be assumed.

| Vehicle | EPA record | A (lbf) | B (lbf/mph) | C (lbf/mph²) | F0 (N) | F1 (N/(m/s)) | F2 (N/(m/s)²) | ETW (lb) |
|---|---|---|---|---|---|---|---|---|
| Tesla Model 3 RWD | MY2024 Model 3 RWD, 3R124-649670 | 27.02 | 0.2873 | 0.0122 | 120.19 | 2.8587 | 0.27155 | 4250 |
| Volvo EX30 Single Motor Extended Range | MY2025 EX30 Single Motor extended range, 202532 | 33.2 | -0.0857 | 0.02006 | 147.68 | -0.8527 | 0.44650 | 4250 |
| Polestar 2 Long Range Single Motor | MY2025 Polestar 2 Single Motor (19 Inch Wheels), 202506 | 35.69 | 0.1104 | 0.01673 | 158.76 | 1.0985 | 0.37238 | 4750 |
| Volkswagen ID.4 Pro (210 kW, RWD) | MY2024 ID.4 Pro, VW316640473 | 27.83 | 0.2217 | 0.01799 | 123.79 | 2.2060 | 0.40043 | 5000 |

Source files and fingerprints:

| File | SHA-256 |
|---|---|
| `24-testcar-2025-05.xlsx` | `e3a5378fa5e6820861d705e36fd2f2046234be8d050026bcfde29f0b8e63a6f9` |
| `25-testcar-2026-01-21.xlsx` | `f131cbb353d0737874e9d61215ba8055b47e4df845f34072bf77faaf780e9dbc` |

**Conversions** use exact definitions (NIST SP 811, 2008, Appendix B and its footnotes 22 and
23): 1 lbf = 4.448 221 615 260 5 N (with standard gravity 9.806 65 m/s²), 1 mph = 0.447 04 m/s,
1 lb = 0.453 592 37 kg. The factors are quoted in `data/reference_values.json` from the
fingerprinted document (<https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication811e2008.pdf>,
SHA-256 `788dd8f0bcb0ec06e40c300690266742532a7e760a93be57764b77ed0ef3482f`), and the tests tie
the model's constants to them.

**Notes on the records.**

- The files also list other wheel versions of two of the test vehicles: the EX30 with 18-inch
  wheels (A = 33.96 lbf and C = 0.02022 lbf/mph², against 33.2 and 0.02006) and the Polestar 2
  with 20-inch wheels, which differs only in the rolling term (A = 39.23 lbf against 35.69).
  The EX30 record for its 19- and 20-inch wheels (19-inch wheels are standard on the Single
  Motor Extended Range, section 6) and the 19-inch Polestar record are used; the other two
  serve as checks (section 7).
- The *drive system* field is unreliable for these cars (the single-motor EX30 and Polestar
  are listed as all-wheel drive, the Model 3 RWD as four-wheel drive). The model names and
  test vehicle IDs identify the cars; the field is not used.
- **Not used:** the file's fuel-economy results. Their unit column reads "MPG" for every row,
  including values that cannot be MPGe for an electric car (the EX30 "Multi-Cycle Test" row
  reads 26.1), and the field definitions on the EPA's page cover only model years 2009 and
  earlier (as retrieved on 27 September 2026). The certificate reports of section 7 later
  showed what the column holds, but they also give the energies directly and with labels, so
  the column is still not needed.

**Pairing EU and US data.** The road load of a car is a property of its body, tyres and
driveline. The model assumes that the EU and US versions of these models share them; the EU
road loads are not public, so the assumption cannot be checked directly (section 9). Two
differences are known and are carried explicitly into the model rather than ignored: the
reference air density (98.21 kPa and 20 °C for the EPA, 1.189 kg/m³ for WLTP) and the test mass
(EPA equivalent test weight versus WLTP test mass).

---

## 4. Regulatory definitions used by the model

Every definition below is quoted in `data/reference_values.json` and checked against its
document by `tools/verify_references.py`; `tests/test_constants.py` ties the model's constants
to those quotes. The documents:

| Document | Copy used | SHA-256 |
|---|---|---|
| UN GTR No. 15, ECE/TRANS/180/Add.15, 12 May 2014 | hosted by TransportPolicy.net (<https://www.transportpolicy.net/wp-content/uploads/2021/08/GTR-No-15.pdf>), because unece.org blocks automated downloads | `2b15775dfc03b1692661ea60e528ac8b9937c189f88674933c190400264c82a1` |
| Commission Regulation (EU) 2017/1151, Official Journal L 175, 7 July 2017 | EU Publications Office, <https://publications.europa.eu/resource/celex/32017R1151> (XHTML, English) | `46244be1b0096bfd73d84d6f67eaf1d16e88ce899d9cb3a7a92af061669f35cb` |
| 40 CFR 1066.305 | eCFR, point-in-time text of 1 September 2026 | `56f0e1dd4d66544e54159c82f413b95dd1658e5bb09e71d496ae21e0772a9814` |
| 40 CFR 86.129-00 | eCFR, point-in-time text of 1 September 2026 | `f58af3d12c5a36746b31547939d66d3d330ec94e5767c2c19b5cb3eecdd2d702` |

| Item | Definition | Reference |
|---|---|---|
| Reference atmospheric conditions (WLTP road load) | p0 = 100 kPa, T0 = 293 K, dry air density ρ0 = 1.189 kg/m³, wind 0 m/s | GTR 15, para. 3.2.9 |
| Mass in running order | the vehicle with its fuel tanks at least 90 % full, including the mass of the driver and liquids, with its standard equipment | GTR 15, para. 3.2.5 |
| Mass of the driver | 75 kg | GTR 15, para. 3.2.6 |
| WLTP test mass | mass in running order + optional equipment (vehicle H) + 25 kg + a representative vehicle load of 15 % of the vehicle load (category 1 vehicles) | GTR 15, Annex 4, para. 4.2.1.3.1 |
| Rotating mass | "may be estimated to be three per cent of the mass in running order plus 25 kg"; in the EU text, "3 per cent of the sum of the mass in running order and 25 kg" (see note below) | GTR 15, Annex 4, para. 4.3.1.4.5; Regulation (EU) 2017/1151, Annex XXI, Sub-Annex 4, para. 2.5.1 |
| EPA equivalent test weight | the test weight basis is "loaded vehicle weight, which is the vehicle weight plus 300 pounds", and the equivalent weight is its class in the table of § 86.129-94(a) | 40 CFR 86.129-00(f)(1) |
| EPA road-load reference conditions | "reference conditions of 20 °C, 98.21 kPa, no wind, no precipitation, and the transmission in neutral" | 40 CFR 1066.305 |

For dry air, `ρ = p / (R·T)` with `R = 287.05 J/(kg·K)` gives 1.1890 kg/m³ at 100 kPa and
293 K, reproducing the GTR value, and 1.1671 kg/m³ at the EPA conditions.

**Note on the rotating mass.** The 2014 GTR wording can be read two ways: 3 % of the sum
(mass in running order + 25 kg), or 3 % of the mass in running order, plus 25 kg. The EU text
of the same rule settles it: "Alternatively, m r may be estimated to be 3 per cent of the sum
of the mass in running order and 25 kg" (Regulation (EU) 2017/1151, Annex XXI, Sub-Annex 4,
para. 2.5.1). The model uses that reading. The other one would add about 24 kg, 1.0-1.2 % of
the inertial mass, and only to the acceleration term. The allowance is a regulatory estimating
convention, not a measurement; leaving it out altogether changes no EU result by more than
0.02 percentage points (docs/method.md, section 5.4).

---

## 5. Physical consistency check

Before any model is built, the official numbers were checked against each other: the energy
the wheels must deliver over the WLTC was computed from the EPA road load as measured (in the
EPA reference air) and the EU WLTP test mass (plus the 3 % rotating mass), and compared with
the official consumption.

| Vehicle | Positive wheel energy (Wh/km) | Official consumption (Wh/km) | Ratio |
|---|---|---|---|
| Tesla Model 3 RWD | 145.5 | 132 | 0.91 |
| Volvo EX30 Single Motor Extended Range | 154.6 | 170 | 1.10 |
| Polestar 2 Long Range Single Motor | 168.1 | 152 | 0.90 |
| Volkswagen ID.4 Pro (210 kW, RWD) | 172.3 | 163 | 0.95 |

A ratio below 1 is expected, not a contradiction: regenerative braking returns part of the
braking energy to the battery, so a car can draw less from the mains than its wheels deliver.
All four ratios sit in the narrow band that plausible drivetrain, regeneration and charging
efficiencies produce; a unit error or a mismatched record would have shown up as an outlier.
The EX30 is the least efficient on this measure, which the model will have to explain rather
than tune away.

---

## 6. Manufacturer data

Manufacturer figures are not needed by the physics (the road load and masses above replace
them), but they are shown to users, so they are held to the same standard. They live in
`data/manufacturer_facts.json`, each with a verbatim quote from its source document.
`tools/verify_manufacturer.py` confirms every document's fingerprint, that every quote and
value really appears in it, and that the column a value was read from is the right variant.

The documents are copyrighted and are not in the repository; the JSON file gives each one's
URL and SHA-256. Where a manufacturer's own site blocks automated access, the documents were
downloaded by hand or read from an Internet Archive copy of the manufacturer's page.

| Vehicle | Item | Value | Source document |
|---|---|---|---|
| Volvo EX30 SM ER | Battery energy | 69 kWh nominal, 65 kWh usable | Volvo price and specification list, MY2025, October 2024 (Ireland); confirmed by the EX30 brochure of 3 November 2025 and a 2024 Volvo press release (69 kWh) |
| Volvo EX30 SM ER | Motor, drive | 200 kW, rear-wheel drive | price and specification list |
| Volvo EX30 SM ER | WLTP consumption, range | 17.0 kWh/100 km, up to 476 km | price and specification list |
| Volvo EX30 SM ER | Masses | 1,850 kg in running order, 1,775 kg minimum kerb, 2,235 kg maximum total | price and specification list |
| Volvo EX30 SM ER | Standard wheels | 19-inch, 245/45 tyres | price and specification list |
| Polestar 2 LR SM (MY24) | Battery energy | 82 kWh ("battery capacity"; gross or usable not stated) | Polestar 2 life cycle assessment report MY23-MY25, 19 November 2024, Tables 9 and 10 |
| Polestar 2 LR SM (MY24) | Motor | 220 kW | same |
| Polestar 2 LR SM (MY24) | WLTP consumption, range | 14.8-15.8 kWh/100 km, 610-655 km | same |
| Polestar 2 LR SM (MY24) | Total weight | 2,009 kg | same |
| Tesla Model 3 RWD (2024) | WLTP range, consumption | 318 mi, 13.2 kWh/100 km | Tesla UK Model 3 page, Internet Archive copy of 14 July 2024 |
| Tesla Model 3 RWD (2024) | Curb mass, wheels | 1,765 kg, 18" or 19" | same |
| Tesla Model 3 RWD (2024) | Battery energy | not published | same page: every "kWh" on it is a consumption unit |
| VW ID.4 Pro | Battery energy | 77 kWh net | Volkswagen Newsroom, *The new high-efficiency drive - all the details*, 10 November 2023 (Internet Archive copy of 6 March 2026) |
| VW ID.4 Pro | Motor, drive, WLTP range | 210 kW, rear-wheel drive, 550 km | same |
| VW ID.4 | Drag coefficient | 0.28 | Volkswagen Newsroom world-premiere and exterior-design releases, 23 September and 27 August 2020 |

**Not published.** Tesla does not publish battery energy. No drag coefficient was found in
any Volvo, Polestar or Tesla document; the model does not need one, because it uses the
measured road load. Figures from third-party websites were not used anywhere.

**Checked against the EU registrations.** The manufacturer documents and the EU data were
collected independently, and they agree:

| Check | Result |
|---|---|
| EX30: mass in running order, consumption and range | 1,850 kg, 170 Wh/km and 476 km in both |
| Polestar 2: total weight plus the 75 kg driver | 2,009 + 75 = 2,084 kg, the EU mass in running order |
| Polestar 2: consumption and range | the EU 5-95 % bands (150-157 Wh/km, 616-649 km) lie inside Polestar's published ranges |
| Model 3: consumption and range | 13.2 kWh/100 km = 132 Wh/km; 318 mi is within one mile of 513 km |
| ID.4 Pro: range | 550 km lies inside the EU 5-95 % band (521-562 km) |
| Motor power: EX30, Polestar 2, ID.4 Pro | 200, 220 and 210 kW in both sources |

The one small difference is informative rather than an error: Tesla's curb mass plus the
75 kg driver gives 1,840 kg against 1,836 kg in the EU data, because "curb mass" is Tesla's
own definition, not the regulatory mass in running order. The model uses the regulatory
value.

---

## 7. Energy at the battery and at the mains (EPA certificates)

**Source.** US EPA, Document Index System, *Certificate Summary Information* reports
(<https://dis.epa.gov/otaqpub/>), one per test group and model year. Electric cars are
certified with SAE J1634 (40 CFR 600.116-12): the test vehicle is driven from full to empty on a
dynamometer set to the road load of section 3, then recharged from the mains. The reports
record, for exactly the test vehicles of section 3, the quantities the model needs to connect
the wheels, the battery and the socket:

| Field in the report | Meaning |
|---|---|
| `Recharge Event Energy` | AC energy taken from the mains to recharge after the test |
| `MCT UBE energy` | usable battery energy: "the total DC discharge energy (Edc total), measured in DC watt-hours for a full discharge test" (40 CFR 600.116-12(a)(8)) |
| `DC energy consumption` | DC energy per mile on the UDDS and highway cycles of the test |
| `Charge Depleting Range` | usable battery energy divided by that consumption |

`tools/epa_certification.py` reads them into `data/epa_certification.json`:

| Vehicle | Report (EPA docid) | Mains | Recharge (kWh) | Usable battery energy (Wh) | DC, UDDS (Wh/mi) | DC, highway (Wh/mi) | Charging efficiency |
|---|---|---|---|---|---|---|---|
| Tesla Model 3 RWD | RTSLV00.0L13-006 (59856), MY2024 | 208 V | 68.879 | 60,997 | 149.6 | 167.7 | 0.8856 |
| Volvo EX30 SM ER | SVVXV00.0Z0D-014 (63199), MY2025, 19 and 20 inch wheels | 233 V | 75.559 | 67,198.7 | 165.56 | 201.16 | 0.8894 |
| Polestar 2 LR SM | SVVXV00.0Z0B-003 (60467), MY2025, 19 inch wheels | 236 V | 92.407 | 82,378 | 171.14 | 201.98 | 0.8915 |
| VW ID.4 Pro | RVGAV00.0VZR-043 (59583), MY2024, D mode (default) | 240 V | 85.869 | 77,411 | 174.6 | 205.0 | 0.9015 |

Charging efficiency is usable battery energy divided by recharge energy, computed here. It
covers everything between the mains and the energy the test draws from the battery: the
charger, the battery's own losses, what the car consumes while it charges, and the drain during
the test's key-off soaks, which the regulation leaves out of the usable energy ("the discharge
energy that occurs during the key-off soak periods is not included in the useable battery
energy", 40 CFR 600.116-12(a)(8)).

**How the values were read and checked.**

- The tool downloads the reports from the EPA (`--download`); repeated downloads are
  byte-identical, and each fingerprint is recorded in the tool.
- The test vehicle ID, the three road-load coefficients and the test weight in each report
  equal those in `data/vehicles.json`, so the energies belong to the same measured car.
- Tesla, Polestar and Volkswagen state the DC consumption of each cycle in the manufacturer's
  comments ("UDDS weighted", "HWFE average", "MCT UBE energy"). For each, usable energy divided
  by consumption reproduces the certified range to the rounding printed, the highway value is
  the mean of the two highway cycles, and, where the report gives the energy of the first UDDS,
  the UDDS value is reproduced by the weighting the reports use: the first UDDS by its share of
  the usable energy, the other three equally.
- Volvo lists the eight phases of the Multi-Cycle Test instead. The tool checks that the phases
  are in the regulatory order (UDDS, highway, UDDS, constant speed, twice; 40 CFR
  600.116-12(a)(2)), adds their DC energies to get the usable energy, applies the same
  weighting, and reproduces both certified ranges to the last printed digit (405.883 and
  334.064 mi).
- One printing error was found and is handled: in the EX30's 18-inch configuration, phase 5 is
  printed as 16.693 kWh/100 mi, but its own energy and distance give 16.544, and only the
  computed value reproduces the certified range (397.177 mi).
- Volkswagen's report exists in three revisions (docids 59581, 59582, 59583); the values used
  are identical in all three, and the latest is cited.

**Further configurations** in the same reports are kept as checks that set nothing: the EX30
with 18-inch wheels (169.09 and 204.19 Wh/mi) and its two 65 mph constant-speed phases
(262.36 and 261.33 Wh/mi; 18-inch: 265.62 and 265.61), the Polestar 2 with 20-inch wheels
(181.33 and 210.69 Wh/mi, rolling term A = 39.23 lbf), and the ID.4 in B mode, its
stronger-regeneration drive mode (171.8 and 204.8 Wh/mi).

**The Test Car List's fuel-economy column** (section 3) is explained by these reports: for the
charge-depleting UDDS and highway rows it is the manufacturer's MPGe ("MFR FE is MPGe
calculated from J1634 tool", Volkswagen report; Tesla's 199.46 appears as 199.5), and for the
EX30's Multi-Cycle Test rows it equals the DC consumption of the last constant-speed phase in
kWh/100 mi, rounded (26.133 as 26.1, 26.561 as 26.6).

**What differs from the EU test.** The EPA recharge was made at 208-240 V (values above); how
each car was recharged in its EU test is not published. The measurements of section 8 show that
charging efficiency depends on the current and on the number of phases (DTU: 87.38 % at 6 A and
91.42 % at 16 A for the same Tesla charger; Reick et al.: 79.58 % single-phase at 10 A and
87.21 % three-phase at 16 A for the same Kia), so the charging efficiency carries over to the EU
only approximately. The test weight and the reference air density also differ; both are handled
explicitly (sections 3 and 4).

---

## 8. Reference values from independent studies

`data/reference_values.json` holds values from official and peer-reviewed sources, each with a
verbatim quote, or the spreadsheet cell, that `tools/verify_references.py` finds in the
fingerprinted document. One sets a model input; the others check the values of section 7.

**Auxiliary load (a model input).** The one energy use the certificates do not separate is the
car's own consumption while it drives (control units, pumps, the 12 V system). In the WLTP test
equipment the car does not need is off: "Auxiliaries shall be switched off or deactivated
during dynamometer operation" (GTR 15, Annex 6, para. 1.2.4.2.2), auxiliaries being "additional
equipment and/or devices not required for vehicle operation" (para. 3.5.1). A US Department of
Energy program record (12 September 2024; Table 2 measured at Argonne National Laboratory's
Advanced Mobility Technology Laboratory, "(ANL AMTL)"; "Independent Reviewers" from Idaho and
Oak Ridge National Laboratories) gives this base consumption for two stationary battery
electric cars at 72 °F with the HVAC drawing 0 W: **226 W and 144 W** ("Other power
consumption", Table 2). The cars are not named in the record.

**Charging efficiency (a check).**

| Source | Value | Relation to the EPA values (0.886-0.902) |
|---|---|---|
| US DOE and EPA, fueleconomy.gov | "often 84% to 93%" | all four lie inside |
| DTU dataset (Sevdari et al. 2023, CC BY 4.0): on-board charger alone, 16 A three-phase | 2020 Tesla Model 3 SR: 91.42 %; 2021 VW ID.4 Pro: 91.07 % | the charger is one link of the chain the EPA measures, so the chain should come out lower; it does (Tesla 0.886, ID.4 0.902), though the charging conditions differ |
| Reick et al. 2021, *Vehicles* (peer reviewed): battery energy over mains energy, Kia e-Niro, 16 A three-phase | 87.21 % | same definition as the EPA value, same range |

**Drivetrain efficiency (a check).** A peer-reviewed study of a 2020 Tesla Model 3 SR+
(Rosenberger et al. 2024, *World Electric Vehicle Journal*) measured a maximum efficiency of
97 % for the car's power unit (power electronics and motor). Any cycle-average battery-to-wheel
efficiency found for the Tesla must be lower.

**Considered and not used.** The fueleconomy.gov page also gives 76.4-80.2 % for the efficiency
of the electric motor "including inverter and gear reduction losses", an assumption based on a
2011 estimate (SAE 2011-01-0887) less 4 % for parasitic losses, older than all four cars. The same
Tesla study shows the shares of energy losses on the WLTP in a bar chart (Figure 8), but on the
WLTP bar only the largest share is labelled, so the others are not read off the chart.

---

## 9. Decisions and open items

**Decided**

- **EPA fuel-economy results are not used** (sections 3 and 7).
- **VW ID.4 Pro instead of ID.3.** The ID.3 is not sold in the United States, so no measured
  road load exists for it; using it would have meant assuming a drag coefficient, a frontal
  area and a rolling-resistance coefficient. The ID.4 Pro has official data on both sides.
  The ID.3 values are kept in `data/vehicles.json` under `considered_but_not_used`.

- **Wheels, battery and mains are bridged with each car's own measurements** (approved
  26 September 2026). The earlier plan took drivetrain, regeneration and charging efficiencies
  from the literature and used one set for every car, because no per-car data were known;
  tuning them per car to the official consumption would have made the comparison circular.
  The EPA certificates of section 7 measure them for exactly these cars, so: the charging
  efficiency of each car comes from its certificate; a drivetrain efficiency and a regeneration
  coefficient per car are identified from its two EPA DC consumptions (UDDS and highway), with
  the auxiliary load of section 8 (the mean of the two measurements, 185 W, with 144 W and
  226 W as bounds); and the model is validated against the EU official values and the EPA
  configurations and speeds not used for identification. The identification uses US data only
  and the validation EU data and unused EPA data, so it stays non-circular. The method and
  its results are in `docs/method.md`.

**Open**

- **The EU road load of each car is not public.** The WLTP coefficients are recorded on each
  car's certificate of conformity (the Tesla study of section 8 lists them from its car's), but
  the EU dataset gives only a road-load family identifier (`RLFI`). The model uses the EPA
  coastdown for both regions, with the air-density correction of section 4.

---

## Reproducing everything

```bash
python tools/check_cycles.py
python tools/verify_cycles.py --download
python tools/eea_query.py "Mk LIKE 'TESLA%' AND Cn LIKE '%MODEL 3%' AND Va = 'H6LR'"
python tools/epa_roadload.py data/sources/24-testcar-2025-05.xlsx 3R124-649670
python tools/build_vehicles.py <folder with the query results> data/vehicles.json
python tools/verify_manufacturer.py
python tools/epa_certification.py --download
python tools/verify_references.py
python tools/update_docs.py --check
python tools/make_figures.py
```

`eea_query.py`, `verify_cycles.py --download` and `epa_certification.py --download` need
internet access; `epa_roadload.py` needs the EPA file downloaded from the link above, and reads
it only if its fingerprint matches the one recorded in `tools/build_vehicles.py`;
`verify_manufacturer.py` and `verify_references.py` need the documents in `data/sources/`,
whose URLs are recorded next to their fingerprints. The tools need `pypdf`, `openpyxl` and
`defusedxml` (`pip install -e ".[tools]"`), and fetch documents through `tools/downloads.py`
(HTTPS only, size-capped, stored only if the fingerprint matches; see SECURITY.md).
The fingerprints confirm each file is the one used here. `update_docs.py --check` confirms that
the tables in README.md and docs/method.md are what the model computes (the tests check the
numbers in the text as well), and `make_figures.py` redraws the figures in docs/images from the
model. `python tools/verify_all.py [--download]` runs all the checks above in one go (the
queries and the figures excepted) and summarises them.
