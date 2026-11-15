"""
Cleaner and parser for the uploaded Canadian dairy mastitis dataset (doi:10.5683/SP2/KIEMHY).
Normalizes farm-level housing, bedding, herd size, and pathogen counts into standard benchmark schemas.
"""

import os
import re
import math
import json
import csv
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any


def col_letter_to_index(col_str: str) -> int:
    exp = 0
    idx = 0
    for char in reversed(col_str):
        idx += (ord(char) - ord('A') + 1) * (26 ** exp)
        exp += 1
    return idx - 1


def parse_xlsx_indexed(path: str) -> List[List[str]]:
    with zipfile.ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                t = si.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')
                strings.append(t.text if t is not None else '')

        tree = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        rows = []
        for r in tree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
            row_dict = {}
            for c in r.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                coord = c.get('r', '')
                m = re.match(r'([A-Z]+)(\d+)', coord)
                if not m:
                    continue
                col_name = m.group(1)
                col_idx = col_letter_to_index(col_name)
                v = c.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                val = v.text if v is not None else ''
                if c.get('t') == 's' and val.isdigit():
                    val = strings[int(val)]
                row_dict[col_idx] = val

            if row_dict:
                max_col = max(row_dict.keys())
                row_list = [row_dict.get(i, '') for i in range(max_col + 1)]
                rows.append(row_list)
        return rows


def clean_mastitis_dataset(
    input_dir: str,
    output_dir: str = "backend-visualization/data/benchmarks"
) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    tot_file = os.path.join(input_dir, "tablemcdv.xlsx")
    sev_file = os.path.join(input_dir, "tablemcSEVEREdv.xlsx")

    rows_tot = parse_xlsx_indexed(tot_file)
    rows_sev = parse_xlsx_indexed(sev_file)

    headers = rows_tot[0]
    tot_dict = {r[0]: r for r in rows_tot[1:] if r and r[0]}
    sev_dict = {r[0]: r for r in rows_sev[1:] if r and r[0]}

    cleaned_records = []
    pathogen_totals = {
        "e_coli": 0, "k_pneumo": 0, "s_aureus": 0, "s_dys": 0, "s_ube": 0
    }

    for fid, r_tot in tot_dict.items():
        r_sev = sev_dict.get(fid, [''] * len(headers))
        if len(r_tot) < len(headers):
            r_tot = r_tot + [''] * (len(headers) - len(r_tot))
        if len(r_sev) < len(headers):
            r_sev = r_sev + [''] * (len(headers) - len(r_sev))

        def safe_float(v, default=0.0):
            try:
                return float(v) if v.strip() else default
            except:
                return default

        def safe_int(v, default=0):
            try:
                return int(float(v)) if v.strip() else default
            except:
                return default

        cows = safe_int(r_tot[1])
        renov_age = safe_float(r_tot[2])
        housing = "free_stall" if safe_int(r_tot[3]) == 1 else "tie_stall"
        bedding_thick = "deep_ge_10cm" if safe_int(r_tot[4]) == 1 else "shallow_lt_10cm"
        bedding_mat = "recycled_manure_solids" if safe_int(r_tot[11]) == 1 else "straw"

        tot_cases = safe_int(r_tot[5])
        sev_cases = safe_int(r_sev[5])

        e_coli = safe_int(r_tot[6])
        k_pneumo = safe_int(r_tot[7])
        s_aureus = safe_int(r_tot[8])
        s_dys = safe_int(r_tot[9])
        s_ube = safe_int(r_tot[10])

        pathogen_totals["e_coli"] += e_coli
        pathogen_totals["k_pneumo"] += k_pneumo
        pathogen_totals["s_aureus"] += s_aureus
        pathogen_totals["s_dys"] += s_dys
        pathogen_totals["s_ube"] += s_ube

        log_ajar = safe_float(r_tot[18])
        cow_days = math.exp(log_ajar) if log_ajar > 0 else cows * 365.0

        ir_tot = (tot_cases / cow_days) * 1000.0 if cow_days > 0 else 0.0
        ir_sev = (sev_cases / cow_days) * 1000.0 if cow_days > 0 else 0.0

        record = {
            "farm_id": f"farm_{int(fid):02d}",
            "lactating_cows": cows,
            "stall_renovation_age_years": renov_age,
            "housing_type": housing,
            "bedding_thickness": bedding_thick,
            "bedding_material": bedding_mat,
            "total_cm_cases": tot_cases,
            "severe_cm_cases": sev_cases,
            "pathogens": {
                "e_coli": e_coli,
                "k_pneumo": k_pneumo,
                "s_aureus": s_aureus,
                "s_dys": s_dys,
                "s_ube": s_ube,
            },
            "animal_days_at_risk": round(cow_days, 1),
            "cm_rate_per_1000_cow_days": round(ir_tot, 3),
            "severe_cm_rate_per_1000_cow_days": round(ir_sev, 3),
        }
        cleaned_records.append(record)

    # Export JSON
    json_path = os.path.join(output_dir, "farm_housing_mastitis_risk.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_dataset": "doi:10.5683/SP2/KIEMHY (Quebec Commercial Dairy Herd Study)",
            "farm_count": len(cleaned_records),
            "farms": cleaned_records,
            "pathogen_distribution": pathogen_totals,
        }, f, indent=2)

    # Export CSV
    csv_path = os.path.join(output_dir, "farm_housing_mastitis_risk.csv")
    fieldnames = [
        "farm_id", "lactating_cows", "stall_renovation_age_years",
        "housing_type", "bedding_thickness", "bedding_material",
        "total_cm_cases", "severe_cm_cases", "e_coli_cases",
        "k_pneumo_cases", "s_aureus_cases", "s_dys_cases", "s_ube_cases",
        "animal_days_at_risk", "cm_rate_per_1000_cow_days", "severe_cm_rate_per_1000_cow_days"
    ]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in cleaned_records:
            row_dict = {
                "farm_id": r["farm_id"],
                "lactating_cows": r["lactating_cows"],
                "stall_renovation_age_years": r["stall_renovation_age_years"],
                "housing_type": r["housing_type"],
                "bedding_thickness": r["bedding_thickness"],
                "bedding_material": r["bedding_material"],
                "total_cm_cases": r["total_cm_cases"],
                "severe_cm_cases": r["severe_cm_cases"],
                "e_coli_cases": r["pathogens"]["e_coli"],
                "k_pneumo_cases": r["pathogens"]["k_pneumo"],
                "s_aureus_cases": r["pathogens"]["s_aureus"],
                "s_dys_cases": r["pathogens"]["s_dys"],
                "s_ube_cases": r["pathogens"]["s_ube"],
                "animal_days_at_risk": r["animal_days_at_risk"],
                "cm_rate_per_1000_cow_days": r["cm_rate_per_1000_cow_days"],
                "severe_cm_rate_per_1000_cow_days": r["severe_cm_rate_per_1000_cow_days"],
            }
            writer.writerow(row_dict)

    return {
        "json_path": json_path,
        "csv_path": csv_path,
        "farms_cleaned": len(cleaned_records),
        "pathogens": pathogen_totals,
    }


if __name__ == "__main__":
    src = "C:/Users/Sophia/.gemini/antigravity/brain/700ff93f-c5d8-4258-8d63-1fb85842f857/scratch/dataset_inspect"
    res = clean_mastitis_dataset(src)
    print("Dataset cleaned successfully:", res)
