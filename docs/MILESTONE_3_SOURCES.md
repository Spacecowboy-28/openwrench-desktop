# Milestone 3 source and dependency research

Reviewed 2026-10-14. Source availability is a dated observation, not a guarantee.
Issue #2 remains the research/acceptance tracker.

## LEMON

- https://lemon-manuals.la/ lists brand/year catalogs and reports temporary hosting.
- https://lemon-manuals.la/Lexus/2015/ explicitly lists GS 350 F Sport AWD and RWD.
- Following the listed AWD URL produced a redirect loop; RWD timed out in this
  research environment. Catalog presence does not prove procedure completeness.
- https://lemon-manuals.la/nfo.html advertises per-car ZIPs and a full torrent,
  and describes commercial-provider origins. These are operator claims.
- https://lemon-manuals.la/about.html links rights-holder objections. No clear
  rights-holder grant for application scraping, indexing or redistribution was
  found. No documented public API was found.
- Integration: explicit browser links only. Both Lexus drivetrain variants remain
  partial matches when drivetrain is unknown. No remote content is copied.

## Operation CHARM

- https://charm.li/ timed out repeatedly. Existing indexed pages identify 2006
  Ford F 150 2WD/4WD Pickup V8-4.6L VIN W references, including:
  https://charm.li/Ford/2006/F%20150%202WD%20Pickup%20V8-4.6L%20VIN%20W/Repair%20and%20Diagnosis/Application%20and%20ID/Vehicle%20Identification%20Number/
- Navigation separates repair/diagnosis, systems, specifications and procedures.
  Root/manual pages were inaccessible here. LEMON describes its CHARM collection
  as older 1982–2013 material; this is not proof of every year's coverage.
- No verified automated-use/redistribution permission or public API established.
  Integration is browser links with intermittent/unverified availability labels.
  F-150 drivetrain and VIN engine designation must match; neither is inferred.

## NHTSA

- Official documentation: https://www.nhtsa.gov/nhtsa-datasets-and-apis
- Year/make/model recalls: https://api.nhtsa.gov/recalls/recallsByVehicle
  with make, model and modelYear query parameters. Results retain campaign IDs,
  publication/report dates, component and summary with an official source link.
- Policy: https://api.nhtsa.gov/ prohibits bulk VIN lookup use. This app performs
  only explicit single year/make/model recall queries, with no VIN disclosure.
  Requests have a 15-second deadline, 10-second transfer timeout, 2 MB cap and
  no followed redirects. No polling, bulk downloads or background sync.
- Manufacturer communications use official portal/dataset links. No communication
  API ingestion is claimed. These are safety/publication references, not complete
  factory repair manuals. No applicability claim substitutes for VIN confirmation.
- Existing vPIC integration remains unchanged. Public access does not establish
  redistribution rights for every manufacturer-authored attachment.

## PDF and search choice

- https://pypdfium2.readthedocs.io/en/stable/readme.html
- https://pypdfium2.readthedocs.io/en/stable/python_api.html
- https://pypi.org/project/pypdfium2/5.14.0/
- pypdfium2 5.14.0 uses PDFium for both extraction and rendering. The selected
  standard wheels omit JavaScript/XFA. It avoids a second PDF parser dependency.
  pypdf's extraction cannot render diagrams; QtPdf requires additional Qt modules
  and their distribution review. No AGPL-only renderer is introduced.
- PDFium is not thread-safe. All desktop PDF work runs in separate QProcess
  workers with timeouts and cancellation; each worker owns its SQLite connection.
- pypdfium2: Apache-2.0/BSD-3-Clause. PDFium: BSD-style plus bundled dependency
  notices. Ship corresponding license files with native builds. No new public
  binary release is authorized.
- SQLite FTS5 provides tokenized page search and snippets without another service.
  Search quotes tokens rather than accepting arbitrary FTS query syntax.
  Scanned PDFs retain their viewable pages but report no extractable text. No OCR.

## Coverage boundary

No preloaded maintenance intervals, capacities, fluid standards or torque values.
No manufacturer technical-data verification is claimed. Users supply their own
lawful documents and schedules, and record publication/provenance information.
Tundra/Civic configuration remains unknown. Lexus engine code 2GR-FSE comes from
Issue #2/user instructions, not an automatic modification of existing records.
Catalog links exist for other makes, but no unverified manual URL is synthesized.
