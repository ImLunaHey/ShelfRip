# Security

If you find a security problem in Shelfrip or in the shared disc database server, please don't open
a public issue. Report it privately from the
[Security tab](https://github.com/Shelfrip/ShelfRip/security/advisories/new) instead, or email
[support@shelfrip.com](mailto:support@shelfrip.com) with "Security" in the subject. We'll reply as soon
as we can.

Useful things to know:

- Shelfrip's web server listens only on `127.0.0.1:8765`, so only your own PC can reach it.
- The shared disc database receives disc fingerprints, title lengths and the names chosen, plus a
  random install id that's stored only as a salted hash. See
  [The shared disc database](README.md#the-shared-disc-database) and [server/](server/).
- Fixes go out in the newest version only. Shelfrip can update itself from Settings › Shelfrip.
