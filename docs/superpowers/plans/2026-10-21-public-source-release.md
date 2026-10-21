# AStockQuant Public Source and Windows Preview Release Plan

> Execute inline; preserve every strategy and existing README/LICENSE. User request dated 2026-10-21 is the specification.

**Goal:** publish checked Python source on main and a GPL-complete, tested Windows Python ZIP on GitHub Releases.
**Architecture:** reuse codex/v8-phase1 v8.3.5 source and verified 75-file Windows payload. Add licensing/source documentation to packaging; no strategy or UI behavior changes. A Windows GitHub Actions run gates a prerelease, using its temporary GITHUB_TOKEN rather than a personal credential.
**Tech stack:** Python 3.11, existing PySide6/pandas application, pytest/unittest, deterministic ZIP builder, GitHub Actions/CLI.

## Constraints

- No reset/checkout/reinitialization or overwriting old data; preserve all strategies and three-tier screening.
- Source, dependencies, build instructions on main; binaries only as Release assets.
- Retain GPL-3.0-only LICENSE and README; preserve third-party terms.
- No sensitive files or cache/account contents in source or ZIP.
- Report offline/Windows CI evidence and network limitations; prerelease only.

## Tasks and completion gates

- [x] 1. Read-only inventory; clone existing GitHub branch after local cleanup; recover old installer. Check 154 tracked files and 301 historical blobs for private paths and common credential patterns. Existing 75 program files byte-match source; original SHA-256 178076bb54eff3d8a01d882d23a7e413be5a8aec00fc150500aaab1f58f2802c.
- [ ] 2. Make test inputs portable and network-independent. Preserve old 63-test baseline validation via ASTOCK_V763_ARCHIVE; skip clearly only if optional old upload absent. Supply short data for every external fallback in the 38-row test. Run full tests and old/new ZIP verification.
- [ ] 3. Extend release contract to require LICENSE, source/build/third-party information. First fail archive contract, then minimal builder/verifier change; preserve all 75 original payload files byte-for-byte. Add BUILDING.md, source mapping, prerelease notes and a recovery report.
- [ ] 4. Commit checkpoint and sync source branch. Merge checked tree into main without replacing README/LICENSE. Windows CI installs dependencies, tests, verifies ZIP, records exact dependency versions/checksums, and publishes v8.3.5-preview.1 only after passing.
- [ ] 5. Verify main source, tag commit, prerelease assets, checksums and download links. Record completed stages and any blocker; never claim manual Windows/network testing.

## Review focus

1. Missing private historical upload: normal public checkout must run without a workspace-specific path; supplied corrupt baseline must fail.
2. Backup market APIs: offline tests must never depend on real provider success/failure.
3. Packaging must include GPL and exact corresponding source access without changing strategy files.
4. CI must stop on test errors, not overwrite existing release assets, and mark release prerelease.
5. Existing main README/LICENSE must be byte-preserved except explicit additive release links; no user data in any artifact.

## Initial findings

- Main 845f767 contains README, LICENSE, .gitignore; full source branch 68ab76d contains 154 files.
- Initial Linux suite: 226 passed, 2 failed (private baseline missing; 38-row test actually reaches AKShare and receives 190 real rows). Desktop and original ZIP each pass 71 tests.
- Native git read works, push lacks credentials; use authorized GitHub Git-data API with expected-head guards for checkpoints. No token is requested or written to disk.
- Original ZIP lacks GPL files (created before license adoption); retain it unchanged and augment distribution metadata through existing builder.
