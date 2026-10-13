# Reuse research

Reviewed 2026-10-13. These are engineering decisions, not claims of tested
interoperability. No automotive project code or manuals were copied.

| Project / primary source | Observed license / status | Useful work | Integration decision |
| --- | --- | --- | --- |
| [LubeLogger](https://github.com/hargata/lubelog) | MIT; releases and issue tracker available | Maintenance, cost and fuel-log concepts | Desktop-native records first. Possible export compatibility later; no .NET server embedded |
| [python-OBD](https://github.com/brendan-w/python-OBD) | GPLv2 per upstream; PyPI 0.7.3 observed | ELM transport, PID decoders, supported-command detection | Strong feature reference. Not imported into this MIT/LGPL build; integration requires licensing review |
| [pyOBD](https://github.com/barracuda-fsh/pyobd) | GPL-2.0; Python 3 remake documented | Desktop diagnostic flows over python-OBD | Evaluate UX and behavior, no source reuse now |
| [FreeDiag](https://github.com/fenugrec/freediag) | GPL-3.0 repository label; native C project | Legacy vehicle transports and scan core | Useful protocol research; not bundled |
| [SavvyCAN](https://github.com/collin80/SavvyCAN) | MIT top-level; Qt app with bundled dependencies, continuous releases available | CAN capture/analysis and visualization | Future capture-file interoperability. Audit bundled licenses before any source reuse |
| [Operation CHARM](https://charm.li/) | Site fetch timed out; redistribution permission not established | Vehicle service-document browsing | No scraping, mirroring, bundling or assumed data license |
| [MCP CHARM](https://github.com/Gonzih/mcp-charm) | README says MIT; small repository, no release verified, no standalone license file observed | Browse/search adapter for CHARM | Not a license grant for underlying manuals. No integration until code grant and content rights are verified |
| [NHTSA vPIC](https://vpic.nhtsa.dot.gov/api/Home/Index) | Official public API and downloadable database | VIN decoding, make/model data | Milestone 2 HTTPS provider with timeout, explicit user request, cache, and manual fallback |
| [NHTSA datasets](https://www.nhtsa.gov/nhtsa-datasets-and-apis) | Official recalls/communications datasets; check each dataset's terms | Recall and manufacturer-communication references | Milestone 3 provider; model-level result is not proof of VIN eligibility |
| [pySerial](https://github.com/pyserial/pyserial) | BSD; mature project, release selection deferred | Portable USB/serial transport | Preferred low-level candidate for milestone 4 |
| [python-can-isotp](https://github.com/pylessard/python-can-isotp) | MIT; source and docs available | ISO 15765 transport | Candidate for later raw-CAN adapters. ELM/STN firmware handles bus protocols initially |
| [pypdf](https://github.com/py-pdf/pypdf) | License file available; exact selected release still to audit | Local PDF text extraction | Candidate for milestone 3 indexing; does not render pages or OCR scanned text |
| [OBDLink developer resources](https://www.obdlink.com/developers/) | Vendor-published documentation | Documented ELM/STN commands | Use authorized commands for later read-only USB integration |

PyOBD's code lists inherit the surrounding license unless a separate grant says
otherwise. No community fault-code dataset has been cleared for redistribution.
Milestone 4 must select a licensed dataset or author sourced descriptions with
independent rights review. Do not import a code dump from an unknown source.

ISO 9141 and ISO 14230 legacy buses matter for older vehicles. ISO 15765/CAN matters
for later vehicles. Initial ELM/STN hardware should handle electrical framing and
protocol detection. The app should request supported PIDs and report unsupported
modes explicitly. An adapter model's marketing claims do not establish vehicle
module coverage in our software. No actual adapter was available in this session.

Prioritize OBDLink EX over USB first. Bluetooth/MX+ introduces pairing, OS-specific
transports and reconnection behavior, so it stays deferred. No ECU write commands,
code clearing, flashing, security access or immobilizer operations belong in the
initial adapter contract.

The four vehicle profiles are development fixtures only. CHARM's MCP README
describes coverage through 2013, so it does not establish coverage for the 2015
Lexus or 2020 Civic. Even within advertised years, configuration and source rights
need independent verification.

Maintenance status above records only visible evidence. A reachable repository
does not prove active support. Before selecting a new runtime dependency, record
its immutable revision, release date, vulnerability review and full license texts.
