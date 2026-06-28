# combustion-air-pollutant-db

This repository builds a CAS-keyed database for combustion-related air pollutants and enriches it with regulatory and toxicology sources.

## What it contains

- A working pollutant table in `outputs/candidate_combustion_pollutants_by_cas_pubchem.csv`
- Source-specific joins from:
  - PubChem / CompTox
  - ATSDR SPL
  - IARC Monographs
  - EPA IRIS
  - NIOSH Pocket Guide
- Supporting combustion profile and SPECIATE-derived inputs

## Pipeline

The main pipeline is:

- `src/extract_combustion_pollutants.py`
- `src/enrich_pollutants_pubchem.py`
- `src/enrich_pollutants_atsdr.py`
- `src/enrich_pollutants_iarc.py`
- `src/enrich_pollutants_iris.py`
- `src/enrich_pollutants_niosh.py`
- `src/build_combustion_pollutants_pipeline.py`

Run the end-to-end pipeline from the project root with:

```bash
./.venv/bin/python src/build_combustion_pollutants_pipeline.py
```

## Outputs

Key outputs are written under `outputs/`:

- `candidate_combustion_pollutants_by_cas.csv`
- `candidate_combustion_pollutants_by_cas_pubchem.csv`
- `candidate_combustion_pollutants_by_cas_pubchem_atsdr.csv`
- `candidate_combustion_pollutants_by_cas_pubchem_iarc.csv`

## Notes

- The repo is intended to stay self-contained around the pipeline code and curated source tables.
- Local virtual environments and cache files are ignored via `.gitignore`.
- Some source files are large raw inputs and should be treated as data assets, not generated outputs.
