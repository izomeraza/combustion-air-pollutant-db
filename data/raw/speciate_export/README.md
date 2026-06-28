# SPECIATE raw export

This directory contains an unfiltered CSV export of the requested SPECIATE tables from `SPECIATE 5.4 2025-09-08.accdb`.

No row filtering, joins, type coercion, or interpretation was applied. Column names and values were preserved as exported by `mdb-export`.

## Exported tables

- `PROFILES.csv`
- `SPECIES.csv`
- `SPECIES_PROPERTIES.csv`
- `PROFILE_REFERENCE_CROSSWALK.csv`
- `REFERENCES.csv`
- `SPECIES_SYNONYMS.csv`
- `tblSpeciesAndConcatSynonyms.csv`
- `tblProfileAndConcatRefs.csv`

## Why each table was exported

- `PROFILES`: core source-profile table. It contains profile-level metadata keyed by `PROFILE_CODE`.
- `SPECIES`: core profile-to-species detail table. It stores species composition records keyed by `(PROFILE_CODE, SPECIES_ID)`.
- `SPECIES_PROPERTIES`: species attribute table. It contains CAS numbers, names, identifiers, and other species-level properties keyed by `SPECIES_ID`.
- `PROFILE_REFERENCE_CROSSWALK`: profile-to-reference link table. It links profile codes to reference codes.
- `REFERENCES`: reference metadata table. It stores reference records keyed by `REF_Code`.
- `SPECIES_SYNONYMS`: species synonym table. It stores alternate descriptors for `SPECIES_ID`.
- `tblSpeciesAndConcatSynonyms`: concatenated species synonym helper table. It appears to provide denormalized synonym text for species records.
- `tblProfileAndConcatRefs`: concatenated profile/reference helper table. It appears to provide denormalized profile metadata with reference text.

## Join keys

The inspected schema shows these join keys and relationship paths:

- `PROFILES.PROFILE_CODE` is the primary key for profiles.
- `SPECIES.PROFILE_CODE` joins to `PROFILES.PROFILE_CODE`.
- `SPECIES.SPECIES_ID` joins to `SPECIES_PROPERTIES.SPECIES_ID` in the schema comments, but that relationship is not enforced.
- `SPECIES_SYNONYMS.SPECIES_ID` joins to `SPECIES_PROPERTIES.SPECIES_ID` by species identifier.
- `tblSpeciesAndConcatSynonyms.SPECIES_ID` aligns with `SPECIES_PROPERTIES.SPECIES_ID` and `SPECIES_SYNONYMS.SPECIES_ID`.
- `PROFILE_REFERENCE_CROSSWALK.PROFILE_CODE` joins to `PROFILES.PROFILE_CODE`.
- `PROFILE_REFERENCE_CROSSWALK.REF_Code` joins to `REFERENCES.REF_Code` in the schema comments, but that relationship is not enforced.
- `tblProfileAndConcatRefs.PROFILE_CODE` aligns with `PROFILES.PROFILE_CODE`.
- `REFERENCES.REF_Code` is the reference identifier used by the crosswalk.

## Intentionally excluded tables

The following candidate tables were identified during schema inspection but were not exported because they were not part of the requested raw export set and appear to be auxiliary, derived, or convenience tables in the schema:

- `ConcatenatedResult`
- `MNEMONIC`
- `List of SVOC Splitting Factors`
- `Oxide Forms`
- `REVISION_LIST`
- `tblLastUpdated`

Rationale:

- `ConcatenatedResult`, `tblProfileAndConcatRefs`, and `MNEMONIC` are profile-oriented helper tables, but only the explicitly requested profile/reference tables were exported.
- `List of SVOC Splitting Factors` and `Oxide Forms` are auxiliary chemistry tables, not part of the requested export set.
- `REVISION_LIST` and `tblLastUpdated` are metadata/change-log tables.

