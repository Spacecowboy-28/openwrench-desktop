# Security

This pre-release stores local data and backups without encryption. VIN lookup
contacts NHTSA only after an explicit Decode action. The form explains the VIN
and year transmission before the button. Requests use HTTPS, refuse redirects,
and have a 15-second deadline. Results remain in a local 30-day cache. Deleting
a vehicle does not purge the independent decode cache. Logs do not record VINs.
Protect the database and backups as private records. No telemetry exists.

No vehicle communication or ECU write operations exist in this version.
The future diagnostic boundary is read-only. Treat malformed documents, adapter
responses, imported archives and community datasets as untrusted inputs.

Once hosted on GitHub, enable private vulnerability reporting in repository
settings before inviting reports. Until then, do not publish secrets, private
documents, VINs or exploit details in public issues. No security contact address
has been established for this new project.

Supported security target: current development branch only. No stable release
or guaranteed support period exists. Review dependencies before binary releases.
