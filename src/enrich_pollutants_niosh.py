#!/usr/bin/env python3
"""Join pollutants with NIOSH Pocket Guide occupational exposure data.

Input:
  outputs/candidate_combustion_pollutants_by_cas_pubchem.csv

Source:
  2005-149.pdf

Output:
  outputs/candidate_combustion_pollutants_by_cas_pubchem.csv

The parser extracts the text-heavy Pocket Guide entries into structured CAS-keyed
records, then joins exact-normalized CAS matches back onto the working CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pypdf import PdfReader


DEFAULT_INPUT = Path("outputs/candidate_combustion_pollutants_by_cas_pubchem.csv")
DEFAULT_PDF = Path("2005-149.pdf")
DEFAULT_OUTPUT = Path("outputs/candidate_combustion_pollutants_by_cas_pubchem.csv")
DEFAULT_CACHE = Path("outputs/.niosh_pocket_guide_cache.json")
CACHE_VERSION = 4

NIOSH_METHOD_TITLES: dict[str, str] = {
    "0500": "PARTICULATES NOT OTHERWISE REGULATED, TOTAL (Grav)",
    "0600": "PARTICULATES NOT OTHERWISE REGULATED, RESPIRABLE (Grav)",
    "0700": "see 9100",
    "0800": "BIOAEROSOL SAMPLING (Indoor Air)",
    "0801": "AEROBIC BACTERIA BY GC-FAME",
    "0900": "MYCOBACTERIUM TUBERCULOSIS, AIRBORNE",
    "1000": "ALLYL CHLORIDE (GC)",
    "1001": "METHYL CHLORIDE (GC)",
    "1002": "CHLOROPRENE (GC)",
    "1003": "HYDROCARBONS, HALOGENATED (GC)",
    "1004": "DICHLOROETHYL ETHER (GC)",
    "1005": "METHYLENE CHLORIDE (GC)",
    "1006": "CHLOROTRICHLOROMETHANE (GC)",
    "1007": "VINYL CHLORIDE (GC)",
    "1008": "ETHYLENE DIBROMIDE (GC)",
    "1009": "VINYL BROMIDE (GC)",
    "1010": "EPICHLOROHYDRIN (GC)",
    "1011": "ETHYL BROMIDE (GC)",
    "1012": "DIFLUORODIBROMOMETHANE (GC)",
    "1013": "PROPYLENE DICHLORIDE (GC)",
    "1014": "METHYL IODIDE (GC)",
    "1015": "VINYLIDENE CHLORIDE (GC)",
    "1016": "1,1,1,2-TETRACHLORO-2,2-DIFLUOROETHANE and 1,1,2,2-TETRACHLORO-1,2-DIFLUOROETHANE (GC)",
    "1017": "BROMOTRIFLUOROMETHANE (GC)",
    "1018": "DICHLORODIFLUOROMETHANE, 1,2-DICHLOROTETRAFLUOROETHANE, CHLORODIFLUOROMETHANE (GC)",
    "1019": "1,1,2,2-TETRACHLOROETHANE (GC)",
    "1024": "1,3-BUTADIENE (GC)",
    "1300": "KETONES I (GC)",
    "1301": "KETONES II (GC)",
    "1302": "N-METHYL-2-PYRROLIDINONE",
    "1400": "ALCOHOLS I (GC)",
    "1401": "ALCOHOLS II (GC)",
    "1402": "ALCOHOLS III (GC)",
    "1403": "ALCOHOLS IV (GC)",
    "1404": "METHYLCYCLOHEXANOL (GC)",
    "1405": "ALCOHOLS COMBINED",
    "1450": "ESTERS I (GC)",
    "1451": "METHYL CELLOSOLVE ACETATE (GC)",
    "1452": "ETHYL FORMATE (GC)",
    "1453": "VINYL ACETATE (GC)",
    "1457": "ETHYL ACETATE (GC)",
    "1454": "ISOPROPYL ACETATE",
    "1455": "XX-Triphenyl phosphate",
    "1456": "see 5037",
    "1458": "METHYL ACETATE (GC)",
    "1459": "METHYL ACRYLATE (GC)",
    "1460": "ISOPROPYL ACETATE (GC)",
    "1500": "HYDROCARBONS, BP 36-126oC (GC)",
    "1501": "HYDROCARBONS, AROMATIC (GC)",
    "1550": "NAPHTHAS (GC)",
    "1551": "TURPENTINE (GC)",
    "1552": "TERPENES",
    "1600": "CARBON DISULFIDE (GC)",
    "1601": "1,1-DICHLORO-1-NITROETHANE (GC)",
    "1602": "DIOXANE (GC)",
    "1603": "ACETIC ACID (GC)",
    "1604": "ACRYLONITRILE (GC)",
    "1605": "XX Ethers I",
    "1606": "ACETONITRILE (GC)",
    "1607": "XX Ethylene Oxide - see 1614",
    "1608": "GLYCIDOL (GC)",
    "1609": "TETRAHYDROFURAN (GC)",
    "1610": "ETHYL ETHER (GC)",
    "1611": "METHYLAL (GC)",
    "1612": "PROPYLENE OXIDE (GC)",
    "1613": "PYRIDINE (GC)",
    "1614": "ETHYLENE OXIDE (GC)",
    "1615": "METHYL tert-BUTYL ETHER (MTBE)(GC)",
    "1616": "n-BUTYL GLYCIDYL ETHER (GC)",
    "1617": "PHENYL ETHER (GC)",
    "1618": "ISOPROPYL ETHER (GC)",
    "1619": "PHENYL GLYCIDYL ETHER (GC)",
    "1620": "ISOPROPYL GLYCIDYL ETHER",
    "2000": "METHANOL (GC)",
    "2001": "XX Cresol - see 2546",
    "2002": "AMINES, AROMATIC (GC)",
    "2003": "1,1,2,2-TETRABROMOETHANE (GC)",
    "2004": "DIMETHYLACETAMIDE and DIMETHYLFORMAMIDE (GC)",
    "2005": "NITROAROMATIC COMPOUNDS (GC)",
    "2007": "AMINOETHANOL COMPOUNDS I (GC)",
    "2008": "CHLOROACETIC ACID (IC)",
    "2009": "XX - see 2540",
    "2010": "AMINES, ALIPHATIC (GC)",
    "2011": "FORMIC ACID (IC)",
    "2012": "n-BUTYLAMINE (GC)",
    "2013": "PHENYL ETHER & DIPHENYL (GC)",
    "2014": "p-CHLOROPHENOL (HPLC)",
    "2015": "CHLOROACETALDEHYDE",
    "2016": "FORMALDEHYDE (HPLC)",
    "2017": "ANILINE, o-TOLUIDINE, AND NITROBENZENE",
    "2018": "ALIPHATIC ALDEHYDES (HPLC)",
    "2500": "METHYL ETHYL KETONE (GC)",
    "2501": "ACROLEIN (GC)",
    "2502": "XX Formaldehyde",
    "2503": "XX Mevinphos - see 5600",
    "2504": "TETRAETHYL PYROPHOSPHATE (TEPP)(GC)",
    "2505": "FURFURYL ALCOHOL (GC)",
    "2506": "ACETONE CYANOHYDRIN (GC)",
    "2507": "NITROGLYCERIN and ETHYLENE GLYCOL DINITRATE (GC)",
    "2508": "ISOPHORONE (GC)",
    "2509": "XX Hydrazine",
    "2510": "1-OCTANETHIOL (GC)",
    "2511": "XX - see 2545",
    "2512": "XX Hexachlorobutadiene",
    "2513": "ETHYLENE CHLOROHYDRIN (GC)",
    "2514": "ANISIDINE (HPLC)",
    "2515": "DIAZOMETHANE (GC)",
    "2516": "DICHLOROFLUOROMETHANE (GC)",
    "2517": "PENTACHLOROETHANE (GC)",
    "2518": "HEXACHLORO-1,3-CYCLOPENTADIENE (GC)",
    "2519": "ETHYL CHLORIDE (GC)",
    "2520": "METHYL BROMIDE",
    "2521": "METHYL CYCLOHEXANONE (GC)",
    "2522": "NITROSAMINES (GC)",
    "2523": "1,3-CYCLOPENTADIENE (GC)",
    "2524": "DIMETHYL SULFATE (GC)",
    "2526": "NITROETHANE (GC)",
    "2527": "NITROMETHANE (GC)",
    "2528": "2-NITROPROPANE (GC)",
    "2529": "FURFURAL (GC)",
    "2530": "DIPHENYL (GC)",
    "2531": "XX Glutaraldehyde - see 2532",
    "2532": "GLUTARALDEHYDE (HPLC)",
    "2533": "TETRAETHYL LEAD, as Pb (GC)",
    "2534": "TETRAMETHYL LEAD, as Pb (GC)",
    "2535": "TOLUENE-2,4-DIISOCYANATE (HPLC)",
    "2536": "VALERALDEHYDE (GC)",
    "2537": "METHYL and ETHYL METHACRYLATE (GC)",
    "2538": "ACETALDEHYDE (GC)",
    "2539": "ALDEHYDES, SCREENING (GC)",
    "2540": "ETHYLENEDIAMINE, DIETHYLENETRIAMINE, and TRIETHYLENETETRAMINE",
    "2541": "FORMALDEHYDE by GC",
    "2542": "MERCAPTANS, METHYL, ETHYL, n-BUTYL (GC)",
    "2543": "HEXACHLOROBUTADIENE (GC/ECD)",
    "2544": "NICOTINE (GC/NPD)",
    "2545": "ALLYL GLYCIDIL ETHER (GC)",
    "2546": "CRESOLS and PHENOL (GC)",
    "2549": "VOLATILE ORGANIC CPDS (SCREENING) (GC/MS)",
    "2550": "BENZOTHIAZOLE IN ASPHALT FUME",
    "2551": "NICOTINE",
    "2552": "METHYL ACRYLATE (GC)",
    "2553": "KETONES II (GC)",
    "2554": "GLYCOL ETHERS (GC)",
    "2555": "KETONES I (GC)",
    "2556": "ISOPHORONE (GC)",
    "2557": "DIACETYL (GC)",
    "2558": "ACETOIN (GC)",
    "2559": "DECABROMODIPHENYL OXIDE (HPLC)",
    "2560": "1-NITROPYRENE in DIESEL PARTICULATES (GC)",
    "2561": "2-(DIMETHYLAMINO)ETHANOL 1-DIMETHYLAMINO-2-PROPANOL (GC)",
    "2562": "1,1,2,2-TETRCHLOROETHANE (GC)",
    "3500": "FORMALDEHYDE (chromotropic acid)(VIS)",
    "3501": "XX Formaldehyde (Girard T)",
    "3503": "HYDRAZINE (VIS)",
    "3504": "XX Hydrazine (color)",
    "3505": "TETRAMETHYL THIOUREA (VIS)",
    "3506": "ACETIC ANHYDRIDE (VIS)",
    "3507": "ACETALDEHYDE (HPLC)",
    "3508": "METHYL ETHYL KETONE PEROXIDE (VIS)",
    "3509": "AMINOETHANOL COMPOUNDS II (IC)",
    "3510": "MONOMETHYLHYDRAZINE (VIS)",
    "3511": "n-METHYLANILINE (GC)",
    "3512": "MALEIC ANHYDRIDE (HPLC)",
    "3513": "TETRANITROMETHANE (GC/NPD)",
    "3514": "ETHYLENIMINE (HPLC)",
    "3515": "1,1-DIMETHYLHYDRAZINE (VIS)",
    "3516": "CROTONALDEHYDE (POL)",
    "3518": "PHENYLHYDRAZINE (VIS)",
    "3700": "BENZENE (portable GC) in exhaled breath and air",
    "3701": "TRICHLOROETHYLENE (portable GC)",
    "3702": "ETHYLENE OXIDE (portable GC)",
    "3703": "METHYLENE CHLORIDE (portable GC)",
    "3704": "PERCHLOROETHYLENE (portable GC)",
    "3800": "ORGANIC & INORGANIC GASES by Extractive FTIR Spectrometry",
    "3900": "Volatile Organic Compounds, C1 to C10, Canister Method",
    "4000": "TOLUENE, passive (GC)",
    "5000": "CARBON BLACK (Gray)",
    "5001": "2,4-D and 2,4,5-T (HPLC)",
    "5002": "WARFARIN (HPLC)",
    "5003": "PARAQUAT (HPLC)",
    "5004": "HYDROQUINONE (HPLC)",
    "5005": "THIRAM (HPLC)",
    "5006": "CARBARYL (SEVIN) (VIS)",
    "5007": "ROTENONE (HPLC)",
    "5008": "PYRETHRUM (HPLC)",
    "5009": "BENZOYL PEROXIDE (HPLC)",
    "5010": "BROMOXYNIL and BROMOXYNIL OCTANOATE (HPLC/GFAAS)",
    "5011": "ETHYLENE THIOUREA (VIS)",
    "5012": "EPN (GC)",
    "5013": "DYES, BENZIDINE, o-ANISIDINE, and o-TOLIDINE (HPLC)",
    "5014": "CHLORINATED TERPHENYL (GC)",
    "5015": "XX Xanthanates",
    "5016": "STRYCHNINE (HPLC)",
    "5017": "DIBUTYL PHOSPHATE (GC)",
    "5018": "2,4,7-TRINITROFLUOREN-9-ONE (HPLC)",
    "5019": "AZELAIC ACID (GC)",
    "5020": "DIBUTYL PHTHALATE and DI(2-ETHYLHEXYL) PHTHALATE (GC)",
    "5021": "o-TERPHENYL (GC)",
    "5022": "ARSENIC, ORGANO- (IC/GFAAS)",
    "5023": "XX Coal Tar Pitch Volatiles",
    "5024": "XX Tetryl",
    "5025": "CHLORINATED DIPHENYL ETHER (GC)",
    "5026": "OIL MIST, MINERAL (IR)",
    "5027": "RIBAVARIN (HPLC)",
    "5028": "XX Picric acid",
    "5029": "4,4'-METHYLENEDIANILINE (MDA)(HPLC)",
    "5030": "CYANURIC ACID (HPLC)",
    "5031": "ASPARTAME (HPLC)",
    "5032": "PENTAMIDINE ISETHIONATE (HPLC)",
    "5033": "p-NITROANILINE (HPLC)",
    "5034": "TRIBUTYL PHOSPHATE (GC)",
    "5035": "SUPER ABSORBENT POLYMER (ICP)",
    "5036": "TRIMELLITIC ANHYDRIDE (GC)",
    "5037": "TRIORTHOCRESYL PHOSPHATE (GC)",
    "5038": "TRIPHENYL PHOSPHATE (GC)",
    "5039": "CHLORINATED CAMPHENE (GC)",
    "5040": "ELEMENTAL CARBON (DIESEL EXHAUST)",
    "5041": "CAPSAICIN & DIHYDROCAPSAICIN (HPLC/FL)",
    "5042": "BENZENE SOLUBLE FRACTION AND TOTAL PARTICULATE (ASPHALT FUME)",
    "5043": "p-TOLUENESULFONIC ACID",
    "5044": "ESTROGENIC COMPOUNDS (HPLC)",
    "5500": "XX Ethylene glycol - see 5523",
    "5501": "XX 4-dimethylaminoazobenzene",
    "5502": "ALDRIN & LINDANE (GC)",
    "5503": "POLYCHLOROBIPHENYLS (GC)",
    "5504": "ORGANOTIN COMPOUNDS, as Sn",
    "5505": "XX Isocyanates",
    "5506": "POLYNUCLEAR AROMATIC HYDROCARBONS (HPLC)",
    "5507": "XX Glutaraldehyde - see 2532",
    "5508": "KEPONE (GC/ECD)",
    "5509": "BENZIDINE and 3,3'-DICHLOROBENZIDINE (HPLC)",
    "5510": "CHLORDANE (GC)",
    "5511": "XX Ronnel - see 5600",
    "5512": "PENTACHLOROPHENOL (HPLC)",
    "5513": "XX Hexachloronaphthalene",
    "5514": "DEMETON (GC)",
    "5515": "POLYNUCLEAR AROMATIC HYDROCARBONS (GC)",
    "5516": "TOLUENEDIAMINES (HPLC)",
    "5517": "POLYCHLOROBENZENES (GC)",
    "5518": "NAPHTHYLAMINES (GC)",
    "5519": "ENDRIN (GC)",
    "5520": "XX Dinitrobenzene & dinitrotoluene",
    "5521": "ISOCYANATES, MONOMERIC (HPLC)",
    "5522": "ISOCYANATES (HPLC/FL)",
    "5523": "GLYCOLS (GC)",
    "5524": "METALWORKING FLUIDS (MWF)",
    "5525": "ISOCYANATES, TOTAL (MAP) (HPLC)",
    "5526": "METHYLTIN CHLORIDES (GC)",
    "5527": "TRIPHENYLTIN CHLORIDES (GC)",
    "5600": "ORGANOPHOSPHOROUS PESTICIDES (GC/FPD)",
    "5601": "ORGANONITROGEN PESTICIDES",
    "5602": "CHLORINATED AND ORGANONITROGEN HERBICIDES (AIR SAMPLING)",
    "5603": "ALACHLOR in Air",
    "5606": "THIOPHENATE-METHYL in Air",
    "5700": "FORMALDEHYDE ON DUST/FIBERS (HPLC)",
    "5701": "RESORCINOL",
    "5800": "POLYCYCLIC AROMATIC COMPOUNDS, TOTAL (PACs)",
    "6000": "XX Mercury - see 6009",
    "6001": "ARSINE (GFAAS)",
    "6002": "PHOSPHINE (UV/VIS)",
    "6003": "XX Tellurium fluoride",
    "6004": "SULFUR DIOXIDE/SULFATE (IC)",
    "6005": "IODINE (IC)",
    "6006": "DIBORANE (PES)",
    "6007": "NICKEL CARBONYL (GFAAS)",
    "6008": "STIBINE (VIS)",
    "6009": "MERCURY (Hopcalite)(cold vapor AAS)",
    "6010": "HYDROGEN CYANIDE (VIS)",
    "6011": "CHLORINE and BROMINE (IC)",
    "6012": "SULFURYL FLUORIDE (GC)",
    "6013": "XX Hydrogen sulfide (IC)",
    "6014": "NITRIC OXIDE/NITROGEN DIOXIDE (VIS)",
    "6015": "AMMONIA (VIS)",
    "6016": "AMMONIA by IC",
    "6017": "HYDROGEN CYANIDE (IC)",
    "6400": "XX Hydrogen sulfide",
    "6401": "XX Phosphorus pentachloride",
    "6402": "PHOSPHORUS TRICHLORIDE (VIS)",
    "6600": "NITROUS OXIDE (portable IR)",
    "6601": "OXYGEN (EC sensor)",
    "6602": "SULFUR HEXAFLUORIDE (portable IR)",
    "6603": "CARBON DIOXIDE (portable GC)",
    "6604": "CARBON MONOXIDE (EC sensor)",
    "6700": "NITROGEN DIOXIDE",
    "6701": "XX Ammonia (pass)",
    "7013": "ALUMINUM (FAAS)",
    "7020": "CALCIUM (FAAS)",
    "7024": "CHROMIUM (FAAS)",
    "7027": "COBALT (FAAS)",
    "7029": "COPPER (FUME/DUST) (FAAS)",
    "7030": "ZINC (ICP)",
    "7048": "CADMIUM (FAAS)",
    "7056": "BARIUM, soluble (FAAS)",
    "7074": "TUNGSTEN, sol/insol (FAAS)",
    "7082": "LEAD (FAAS)",
    "7101": "XX Vanadium, sol/insol (ICP)",
    "7102": "BERYLLIUM (GFAAS)",
    "7103": "XX Rhodium - see 7300",
    "7104": "XX Platinum - see 7300",
    "7105": "LEAD (GFAAS)",
    "7300": "ELEMENTS (ICP)",
    "7301": "ELEMENTS by ICP (Aqua Regia Ashing)",
    "7303": "ELEMENTS by ICP (Hot Block/HCl/HNO3 Digestion)",
    "7400": "ASBESTOS and other FIBERS by PCM",
    "7401": "ALKALINE DUST (titration)",
    "7402": "ASBESTOS by TEM",
    "7403": "see 9002",
    "7404": "CELLULOSE INSULATION",
    "7500": "SILICA (XRD)",
    "7501": "SILICA, AMORPHOUS (XRD)",
    "7502": "ZINC OXIDE (XRD)",
    "7503": "XX Talc",
    "7504": "VANADIUM OXIDES (XRD)",
    "7505": "LEAD SULFIDE (XRD)",
    "7506": "BORON CARBIDE (XRD)",
    "7600": "CHROMIUM, HEXAVALENT (VIS)",
    "7601": "SILICA (VIS)",
    "7602": "SILICA (IR)",
    "7603": "SILICA IN COAL MINE DUST (IR)",
    "7604": "CHROMIUM, HEXAVALENT (IC)",
    "7605": "CHROMIUM, HEXAVALENT by ION CHROMATOGRAPHY",
    "7700": "LEAD by Chemical Spot Test",
    "7701": "LEAD by ULTRASOUND/ASV",
    "7702": "LEAD by FIELDPORTABLE XRF",
    "7703": "CHROMIUM, HEXAVALENT by FIELD PORTABLE SPECTROPHOTOMETRY",
    "7900": "ARSENIC (HYDRIDE AAS)",
    "7901": "ARSENIC TRIOXIDE (GFAAS)",
    "7902": "FLUORIDES by ISE",
    "7903": "ACIDS, INORGANIC (IC)",
    "7904": "CYANIDES (ISE)",
    "7905": "PHOSPHORUS (GC)",
    "7906": "FLUORIDES by IC",
    "8300": "HIPPURIC ACID in urine (VIS)",
    "8301": "HIPPURIC and METHYL HIPPURIC ACIDS in urine (HPLC)",
    "8302": "MBOCA in urine",
    "8303": "PENTACHLOROPHENOL in urine",
    "8305": "PHENOL & p-CRESOL in urine",
    "8306": "BENZIDINE in urine (GC)",
    "8308": "FLUORIDE in urine",
    "8310": "METALS in urine (ICP)",
    "8315": "TRIAZINE HERBICIDES and their METABOLITES",
    "8317": "ANALINE and o-TOLUDINE in urine",
    "9000": "ASBESTOS, CHRYSOTILE by XRD",
    "9002": "ASBESTOS (bulk) by PLM",
    "9101": "CHROMIUM (VI) in settled dust (Test Kit)",
    "9102": "ELEMENTS on WIPES (ICP)",
    "9105": "LEAD in DUST WIPES by Chemical Spot Test",
    "9106": "METHAMPHETAMINE and Illicit Drugs, Precursors and Adulterants on Wipes by Liquid-Liquid Extraction",
    "9109": "ALPHA-EMITTERS in Urine",
    "9110": "CAESIUM-137 in Urine",
    "9111": "LEAD in Dust Wipes by ICP",
    "9200": "CHLORINATED and ORGANONITROGEN HERBICIDES (HAND WASH)",
    "9201": "CHLORINATED and ORGANONITROGEN HERBICIDES (DERMAL PATCH)",
    "9202": "CAPTAN and THIOPHENATE-METHYL (HAND RINSE)",
    "9205": "CAPTAN and THIOPHENATE-METHYL (DERMAL PATCH)",
}

ENTRY_START_RE = re.compile(r"(?m)^\s*(?P<name>.+?)\s+Formula:\s+")
SECTION_END_MARKERS = (
    "Physical Description:",
    "Chemical & Physical Properties:",
    "Chemical & Physical",
    "Personal Protection/Sanitation",
    "Respirator Recommendations",
    "Exposure Routes, Symptoms, Target Organs",
    "First Aid",
    "Chemical and Physical Properties:",
)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv_atomic(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_cas(value: str) -> str:
    return re.sub(r"[^0-9]", "", (value or "").strip())


def append_missing(fieldnames: list[str], candidates: list[str]) -> list[str]:
    out = list(fieldnames)
    for candidate in candidates:
        if candidate not in out:
            out.append(candidate)
    return out


def read_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def split_entries(pdf_text: str) -> list[str]:
    matches = list(ENTRY_START_RE.finditer(pdf_text))
    entries: list[str] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(pdf_text)
        chunk = pdf_text[start:end].strip()
        if chunk:
            entries.append(chunk)
    return entries


def extract_between(text: str, start_pattern: str, end_patterns: tuple[str, ...]) -> str:
    start_match = re.search(start_pattern, text, re.I | re.S)
    if not start_match:
        return ""
    start = start_match.end()
    end = len(text)
    for marker in end_patterns:
        marker_match = re.search(re.escape(marker), text[start:], re.I | re.S)
        if marker_match:
            candidate = start + marker_match.start()
            if candidate < end:
                end = candidate
    return normalize_text(text[start:end])


def split_labeled_values(block: str, labels: tuple[str, ...]) -> dict[str, str]:
    if not block:
        return {label: "" for label in labels}
    pattern = re.compile(r"(?i)\b(" + "|".join(re.escape(label) for label in labels) + r")(?:[\*†])?\s*:")
    matches = list(pattern.finditer(block))
    if not matches:
        return {label: "" for label in labels}
    out: dict[str, str] = {label: "" for label in labels}
    for idx, match in enumerate(matches):
        label = normalize_text(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        out[label] = normalize_text(block[start:end])
    return out


def expand_niosh_methods(raw_methods: str) -> str:
    if not raw_methods:
        return ""

    raw_methods = re.sub(r"(?<=\S)\s+OSHA\b", " | OSHA", raw_methods)
    expanded_segments: list[str] = []
    for group in raw_methods.split(" | "):
        group = normalize_text(group)
        if not group:
            continue

        if group.startswith("NIOSH ") and not re.search(r"\bNIOSH\s+[0-9]{4}\b", group):
            expanded_segments.append(normalize_text(group.removeprefix("NIOSH ")))
            continue

        tokens = [token.strip() for token in group.split(",")]
        current_prefix = ""
        for token in tokens:
            if not token:
                continue
            m = re.match(r"(?i)^(?:NIOSH\s+)?([0-9]{4})(\s*\(adapt\))?(.*)$", token)
            if m:
                current_prefix = "NIOSH"
                code = m.group(1)
                suffix = m.group(2) or ""
                tail = normalize_text(m.group(3))
                title = NIOSH_METHOD_TITLES.get(code, f"NIOSH {code}")
                if suffix:
                    title = f"{title}{suffix}"
                if tail:
                    title = f"{title} {tail}"
                expanded_segments.append(title)
                continue

            m = re.match(r"^([0-9]{4})(\s*\(adapt\))?$", token)
            if m and current_prefix == "NIOSH":
                code = m.group(1)
                suffix = m.group(2) or ""
                title = NIOSH_METHOD_TITLES.get(code, f"NIOSH {code}")
                if suffix:
                    title = f"{title}{suffix}"
                expanded_segments.append(title)
                continue

            expanded_segments.append(token)

    return " | ".join(expanded_segments)


def parse_entry(chunk: str) -> dict[str, str]:
    out = {
        "niosh_chemical_name": "",
        "niosh_formula": "",
        "niosh_casrn": "",
        "niosh_rtecs": "",
        "niosh_idlh": "",
        "niosh_conversion": "",
        "niosh_dot": "",
        "niosh_synonyms": "",
        "niosh_exposure_limits_raw": "",
        "niosh_rel": "",
        "niosh_osha_pel": "",
        "measurement_methods": "",
        "niosh_incompatibilities_reactivities": "",
    }

    m_name = re.search(r"(?s)^\s*(.*?)\s+Formula:\s*", chunk)
    if m_name:
        out["niosh_chemical_name"] = normalize_text(m_name.group(1))

    m_formula = re.search(r"(?s)Formula:\s*(.*?)\s+CAS#:\s*", chunk)
    if m_formula:
        out["niosh_formula"] = normalize_text(m_formula.group(1))

    m_cas = re.search(r"(?s)CAS#:\s*(.*?)\s+RTECS#:\s*", chunk)
    if m_cas:
        out["niosh_casrn"] = normalize_text(m_cas.group(1))

    m_rtecs = re.search(r"(?s)RTECS#:\s*(.*?)\s+IDLH:\s*", chunk)
    if m_rtecs:
        out["niosh_rtecs"] = normalize_text(m_rtecs.group(1))

    m_idlh = re.search(r"(?s)IDLH:\s*(.*?)\s+Conversion:\s*", chunk)
    if m_idlh:
        out["niosh_idlh"] = normalize_text(m_idlh.group(1))

    m_conversion = re.search(r"(?s)Conversion:\s*(.*?)\s+DOT:\s*", chunk)
    if m_conversion:
        out["niosh_conversion"] = normalize_text(m_conversion.group(1))

    m_dot = re.search(r"(?s)DOT:\s*(.*?)\s+Synonyms/Trade Names:\s*", chunk)
    if m_dot:
        out["niosh_dot"] = normalize_text(m_dot.group(1))

    m_syn = re.search(r"(?s)Synonyms/Trade Names:\s*(.*?)\s+Exposure Limits:\s*", chunk)
    if m_syn:
        out["niosh_synonyms"] = normalize_text(m_syn.group(1))

    m_limits = re.search(
        r"(?is)Exposure Limits:\s*(.*?)(?=Measurement Methods|Physical Description:|Chemical\s*&\s*Physical(?:\s+Properties)?:|Personal Protection/Sanitation|Respirator Recommendations|Exposure Routes, Symptoms, Target Organs|First Aid|$)",
        chunk,
    )
    if m_limits:
        block = normalize_text(m_limits.group(1))
        out["niosh_exposure_limits_raw"] = block
        labeled = split_labeled_values(block, ("NIOSH REL", "OSHA PEL"))
        out["niosh_rel"] = labeled.get("NIOSH REL", "")
        out["niosh_osha_pel"] = labeled.get("OSHA PEL", "")

    m_methods = re.search(
        r"(?is)Measurement Methods(?:\s*\(see Table 1\):|\s*:)?\s*(.*?)(?=Physical Description:|Chemical\s*&\s*Physical(?:\s+Properties)?:|Personal Protection/Sanitation|Respirator Recommendations|Incompatibilities and Reactivities|Exposure Routes, Symptoms, Target Organs|First Aid|$)",
        chunk,
    )
    if m_methods:
        out["measurement_methods"] = normalize_text(m_methods.group(1))

    m_incompat = re.search(
        r"(?is)Incompatibilities and Reactivities:\s*(.*?)(?=Exposure Routes, Symptoms, Target Organs|First Aid|Chemical & Physical Properties:|Personal Protection/Sanitation|Respirator Recommendations|$)",
        chunk,
    )
    if m_incompat:
        out["niosh_incompatibilities_reactivities"] = normalize_text(m_incompat.group(1))

    return out


def load_or_parse_niosh(pdf_path: Path, cache_path: Path) -> list[dict[str, str]]:
    cache = load_json(cache_path)
    stat = pdf_path.stat()
    if (
        cache.get("cache_version") == CACHE_VERSION
        and cache.get("source_path") == str(pdf_path)
        and cache.get("source_mtime_ns") == stat.st_mtime_ns
        and cache.get("source_size") == stat.st_size
        and isinstance(cache.get("records"), list)
    ):
        return [row for row in cache["records"] if isinstance(row, dict)]

    pdf_text = read_pdf_text(pdf_path)
    entries = split_entries(pdf_text)
    records = [parse_entry(chunk) for chunk in entries]
    write_json_atomic(
        cache_path,
        {
            "cache_version": CACHE_VERSION,
            "source_path": str(pdf_path),
            "source_mtime_ns": stat.st_mtime_ns,
            "source_size": stat.st_size,
            "records": records,
        },
    )
    return records


def build_index(records: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_cas: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in records:
        cas = normalize_cas(row.get("niosh_casrn", ""))
        if cas:
            by_cas[cas].append(row)
    return by_cas


def merge_records(records: list[dict[str, str]]) -> dict[str, str]:
    if not records:
        return {
            "niosh_chemical_name": "",
            "niosh_formula": "",
            "niosh_casrn": "",
            "niosh_rtecs": "",
            "niosh_idlh": "",
            "niosh_conversion": "",
            "niosh_dot": "",
            "niosh_synonyms": "",
            "niosh_exposure_limits_raw": "",
            "niosh_rel": "",
            "niosh_osha_pel": "",
            "measurement_methods": "",
            "measurement_methods_expanded": "",
            "niosh_incompatibilities_reactivities": "",
            "niosh_match_count": "0",
        }

    def unique_join(key: str) -> str:
        values: list[str] = []
        for row in records:
            value = normalize_text(row.get(key, ""))
            if value and value not in values:
                values.append(value)
        return " | ".join(values)

    raw_methods = unique_join("measurement_methods")
    return {
        "niosh_chemical_name": unique_join("niosh_chemical_name"),
        "niosh_formula": unique_join("niosh_formula"),
        "niosh_casrn": unique_join("niosh_casrn"),
        "niosh_rtecs": unique_join("niosh_rtecs"),
        "niosh_idlh": unique_join("niosh_idlh"),
        "niosh_conversion": unique_join("niosh_conversion"),
        "niosh_dot": unique_join("niosh_dot"),
        "niosh_synonyms": unique_join("niosh_synonyms"),
        "niosh_exposure_limits_raw": unique_join("niosh_exposure_limits_raw"),
        "niosh_rel": unique_join("niosh_rel"),
        "niosh_osha_pel": unique_join("niosh_osha_pel"),
        "measurement_methods": raw_methods,
        "measurement_methods_expanded": expand_niosh_methods(raw_methods),
        "niosh_incompatibilities_reactivities": unique_join("niosh_incompatibilities_reactivities"),
        "niosh_match_count": str(len(records)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Join combustion pollutants with NIOSH Pocket Guide data.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"input file not found: {args.input}")
    if not args.pdf.exists():
        raise SystemExit(f"NIOSH PDF not found: {args.pdf}")

    input_rows = read_csv_dicts(args.input)
    records = load_or_parse_niosh(args.pdf, args.cache)
    index = build_index(records)

    base_fieldnames = [
        name
        for name in input_rows[0].keys()
        if name not in {"niosh_measurement_methods", "niosh_measurement_methods_expanded", "niosh_measurement_methods_raw"}
    ]
    fieldnames = append_missing(
        base_fieldnames,
        [
            "niosh_chemical_name",
            "niosh_formula",
            "niosh_casrn",
            "niosh_rtecs",
            "niosh_idlh",
            "niosh_conversion",
            "niosh_dot",
            "niosh_synonyms",
            "niosh_exposure_limits_raw",
            "niosh_rel",
            "niosh_osha_pel",
            "measurement_methods",
            "measurement_methods_expanded",
            "niosh_incompatibilities_reactivities",
            "niosh_match_count",
        ],
    )

    joined_rows: list[dict[str, str]] = []
    matched_rows = 0
    matched_cas: set[str] = set()
    for row in input_rows:
        cas = normalize_cas(row.get("cas", ""))
        matched = index.get(cas, [])
        enriched = dict(row)
        enriched.update(merge_records(matched))
        enriched.pop("niosh_measurement_methods", None)
        enriched.pop("niosh_measurement_methods_expanded", None)
        joined_rows.append(enriched)
        if matched:
            matched_rows += 1
            matched_cas.add(cas)

    write_csv_atomic(args.output, joined_rows, fieldnames)
    total = len(input_rows)
    print(f"wrote {len(joined_rows)} rows to {args.output}")
    print(f"matched rows: {matched_rows}/{total} ({matched_rows / total:.1%})")
    print(f"matched unique CAS: {len(matched_cas)}")
    print(f"parsed records: {len(records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
