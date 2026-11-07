"""Build data/countries.json (country names, currency) from Unicode CLDR via Babel.

Run once when updating:  python tools/make_countries.py
"""
import json
from pathlib import Path

import babel.numbers as bn
from babel import Locale

# Standard VAT / GST rates that are well established (check locally; some countries
# have reduced rates for construction or regional sales taxes instead).
TAX = {"SA": ("VAT", 15), "AE": ("VAT", 5), "OM": ("VAT", 5), "BH": ("VAT", 10), "QA": ("VAT", 0),
       "KW": ("VAT", 0), "EG": ("VAT", 14), "JO": ("Sales tax", 16), "TR": ("VAT", 20),
       "GB": ("VAT", 20), "IE": ("VAT", 23), "DE": ("VAT", 19), "FR": ("VAT", 20), "ES": ("VAT", 21),
       "IT": ("VAT", 22), "NL": ("VAT", 21), "BE": ("VAT", 21), "PT": ("VAT", 23), "ZA": ("VAT", 15),
       "NG": ("VAT", 7.5), "KE": ("VAT", 16), "AU": ("GST", 10), "NZ": ("GST", 15), "SG": ("GST", 9),
       "US": ("Sales tax", 0), "CA": ("GST", 5), "IN": ("GST", 18), "PK": ("Sales tax", 0)}

SKIP = {"ZZ", "EU", "EZ", "UN", "XA", "XB", "XK", "QO", "AQ", "BV", "HM", "TF", "UM", "CP", "DG", "IC", "EA", "TA", "AC"}


def main():
    en, ar = Locale("en"), Locale("ar")
    out = []
    for code, name in sorted(en.territories.items(), key=lambda kv: kv[1]):
        if len(code) != 2 or not code.isalpha() or code in SKIP:
            continue
        cur = bn.get_territory_currencies(code)
        if not cur:
            continue
        tax = TAX.get(code)
        out.append({"code": code, "name": name, "name_ar": ar.territories.get(code, name),
                    "currency": cur[0],
                    "currency_name": bn.get_currency_name(cur[0], locale="en"),
                    "tax_name": tax[0] if tax else "VAT/GST", "tax_pct": tax[1] if tax else None})
    path = Path(__file__).resolve().parent.parent / "data" / "countries.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(len(out), "countries ->", path)


if __name__ == "__main__":
    main()
