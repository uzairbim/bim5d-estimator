"""Write indicative ("assumed") resource prices per region to data/prices/<REGION>.csv.

These are typical market levels around late 2026, estimated without live quotes. Prices change
daily, so they are a starting point only: the app labels them "assumed" and keeps them apart from
prices the user confirms. Run:  python tools/make_assumed_prices.py
Existing rows the user has entered (source not starting with ASSUMED) are kept.
"""
import csv
from pathlib import Path

DATE = "2026-11"
SOURCE = f"ASSUMED indicative market price {DATE} - verify"

# Saudi Arabia (SAR). All-in labour cost to the contractor per hour.
SA = {
    "L-SKL": 22, "L-UNS": 14,
    "P-EXC": 220, "P-TRUCK": 150, "P-PUMP": 450, "P-VIB": 15, "P-PILE": 1500, "P-CRANE": 450, "P-COMP": 40,
    "M-RMC": 230, "M-CEM": 15, "M-SND": 45, "M-AGG": 60, "M-RBR": 3300, "M-WIRE": 6, "M-MESH": 12,
    "M-PE": 2, "M-PLY": 40, "M-TMB": 1800, "M-BLK": 2.5, "M-BRK": 1.5, "M-INS": 25, "M-GYP": 18,
    "M-STUD": 8, "M-PNT": 14, "M-PRM": 12, "M-EPNT": 22, "M-SPNT": 35, "M-TILE": 55, "M-WTILE": 45,
    "M-ADH": 1.2, "M-GRT": 5, "M-WOOD": 140, "M-CLGSYS": 25, "M-WPM": 35, "M-WPC": 30, "M-STL": 7500,
    "M-RAIL": 350, "M-CLAD": 350, "M-DOOR": 1500, "M-WIN": 750, "M-CWP": 750, "M-CWM": 140,
    "M-STAIR": 7000, "M-LIFT": 120000, "M-FFE": 1200, "M-PIPE-S": 25, "M-PIPE-M": 120, "M-PIPE-L": 350,
    "M-PFIT": 30, "M-VALVE": 250, "M-SAN": 1500, "M-SPRK": 70, "M-GALV": 9, "M-DIFF": 220,
    "M-MECH": 12000, "M-TRAY": 45, "M-TFIT": 35, "M-CBL": 8, "M-LUM": 250, "M-ACC": 35, "M-DB": 2500,
    "M-APPL": 2500, "M-PNL": 12000, "M-CTRL": 500, "M-GEN": 800, "M-LINT": 45, "M-SILL": 120, "M-SEAL": 18,
    "M-SKRT": 25, "M-HRD": 35, "M-PINS": 20, "M-DINS": 35, "M-TERM": 5,
    "M-JOIN": 1100, "M-PV": 650, "M-MECH-S": 1500,
    "M-BIT": 6, "M-TBLK": 4.5, "M-STONE": 130, "M-RTILE": 35, "M-HORDI": 3.5, "M-DRAIN": 120, "M-FIRE": 900, "M-MH": 1500, "M-POWER": 110000, "M-POWER-S": 25000, "M-MARBLE": 160, "M-PAVER": 32,
}

# UAE (AED): close to Saudi levels, slightly higher.
AE = {k: round(v * (1.1 if k.startswith("L-") else 1.05), 2) for k, v in SA.items()}

PK = {  # Pakistan (PKR)
    "L-SKL": 400, "L-UNS": 225, "P-EXC": 9000, "P-TRUCK": 5000, "P-PUMP": 15000, "P-CRANE": 15000,
    "M-RMC": 22000, "M-CEM": 1450, "M-SND": 3500, "M-AGG": 5000, "M-RBR": 270000, "M-BLK": 70,
    "M-BRK": 18, "M-PLY": 1700, "M-TMB": 150000, "M-PNT": 1200, "M-PRM": 900, "M-TILE": 2500,
    "M-WTILE": 2200, "M-GYP": 900, "M-STL": 450000, "M-DOOR": 45000, "M-WIN": 18000, "M-WPM": 1500,
    "M-SAN": 30000, "M-LUM": 3500, "M-ACC": 600, "M-CBL": 250,
}

IN = {  # India (INR)
    "L-SKL": 110, "L-UNS": 70, "P-EXC": 2000, "P-TRUCK": 1200, "P-PUMP": 4000, "P-CRANE": 4000,
    "M-RMC": 6000, "M-CEM": 380, "M-SND": 1800, "M-AGG": 1600, "M-RBR": 62000, "M-BLK": 45,
    "M-BRK": 9, "M-PLY": 900, "M-TMB": 60000, "M-PNT": 300, "M-PRM": 220, "M-TILE": 900,
    "M-WTILE": 800, "M-GYP": 350, "M-STL": 110000, "M-DOOR": 18000, "M-WIN": 8000, "M-WPM": 600,
    "M-SAN": 12000, "M-LUM": 1500, "M-ACC": 250, "M-CBL": 90,
}

GB = {  # United Kingdom (GBP)
    "L-SKL": 32, "L-UNS": 22, "P-EXC": 75, "P-TRUCK": 60, "P-PUMP": 140, "P-CRANE": 150,
    "M-RMC": 140, "M-CEM": 12, "M-SND": 48, "M-AGG": 45, "M-RBR": 900, "M-BLK": 2.2, "M-BRK": 0.75,
    "M-PLY": 22, "M-TMB": 650, "M-PNT": 7, "M-PRM": 6, "M-TILE": 30, "M-WTILE": 28, "M-GYP": 4,
    "M-STL": 2800, "M-DOOR": 450, "M-WIN": 450, "M-WPM": 18, "M-SAN": 350, "M-LUM": 70, "M-ACC": 10,
    "M-CBL": 2, "M-CWP": 420, "M-CWM": 60,
}

DE = {  # Germany (EUR)
    "L-SKL": 48, "L-UNS": 38, "P-EXC": 85, "P-TRUCK": 70, "P-PUMP": 160, "P-CRANE": 160,
    "M-RMC": 150, "M-CEM": 9, "M-SND": 35, "M-AGG": 30, "M-RBR": 950, "M-BLK": 2.5, "M-BRK": 0.9,
    "M-PLY": 25, "M-TMB": 600, "M-PNT": 8, "M-PRM": 7, "M-TILE": 30, "M-WTILE": 28, "M-GYP": 5,
    "M-STL": 3000, "M-DOOR": 550, "M-WIN": 500, "M-WPM": 20, "M-SAN": 450, "M-LUM": 80, "M-ACC": 12,
    "M-CBL": 2.5, "M-CWP": 450, "M-CWM": 65,
}

US = {  # United States (USD)
    "L-SKL": 45, "L-UNS": 32, "P-EXC": 140, "P-TRUCK": 100, "P-PUMP": 200, "P-CRANE": 220,
    "M-RMC": 165, "M-CEM": 15, "M-SND": 35, "M-AGG": 40, "M-RBR": 1100, "M-BLK": 2.2, "M-BRK": 0.7,
    "M-PLY": 32, "M-TMB": 700, "M-PNT": 10, "M-PRM": 8, "M-TILE": 25, "M-WTILE": 25, "M-GYP": 6,
    "M-STL": 3200, "M-DOOR": 500, "M-WIN": 450, "M-WPM": 15, "M-SAN": 500, "M-LUM": 90, "M-ACC": 12,
    "M-CBL": 2.5, "M-CWP": 600, "M-CWM": 85,
}

PACKS = {"SA": SA, "AE": AE, "PK": PK, "IN": IN, "GB": GB, "DE": DE, "US": US}


def main():
    folder = Path(__file__).resolve().parent.parent / "data" / "prices"
    folder.mkdir(exist_ok=True)
    for region, prices in PACKS.items():
        path = folder / f"{region}.csv"
        keep = {}
        if path.is_file():
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    if not str(r.get("source", "")).upper().startswith("ASSUMED"):
                        keep[r["resource"]] = r          # user's own prices win
        rows = [{"resource": k, "price": v, "source": SOURCE, "date": DATE}
                for k, v in prices.items() if k not in keep] + list(keep.values())
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["resource", "price", "source", "date"])
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: r["resource"]))
        print(region, len(rows), "prices ->", path.name)


if __name__ == "__main__":
    main()
