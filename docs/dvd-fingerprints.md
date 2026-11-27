# DVD fingerprint compatibility

The proposed DVD recipe includes only files directly in `VIDEO_TS` whose extensions
are `.IFO`, `.BUP` or `.VOB` (case-insensitive). It preserves the existing filename
sort order and MD5 over little-endian 64-bit file sizes. Blu-ray hashing is unchanged.
This matches the file selection in the
[TheDiscDB specification](https://github.com/TheDiscDb/optical-disc-manifest/blob/main/specification/v1/README.md).

Previously, every file directly in `VIDEO_TS` contributed to the hash. DVDs containing
only standard files retain their hashes. DVDs with additional files receive different
hashes, on Windows as well as other platforms. A folder containing only unrelated
files no longer produces a DVD fingerprint.

Existing catalog entries, saved rip metadata and shared-database records are not
rewritten. An old hash for a disc with additional files will not match a new filtered
hash. The old digest alone cannot be converted: the original file sizes or disc are
needed. Compatibility handling for those records must be agreed before release.
