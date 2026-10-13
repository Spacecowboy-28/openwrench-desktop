# Contribution schemas

Milestone 3 will introduce versioned JSON schemas and a validator for repair data.
No repair dataset is accepted or described as verified in this foundation build.

Required design fields: source identifier, source reference, reuse license,
vehicle year/make/model/engine/trim applicability, verification status, reviewer,
review date, units, and schema version. An unknown configuration stays null.

The `SourceRecord` protocol in `src/openwrench/providers.py` establishes the
first internal boundary. It is not yet a complete external contribution schema.
