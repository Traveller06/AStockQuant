# Publication recovery — 2026-10-21

Repository: Traveller06/AStockQuant. Original full-source head: 68ab76dc605859e258ced85f77fa24c1f7fbfcd4. Original main: 845f7677d13313cfd7ecf9131d42527fd35e6e31.

Plan: docs/superpowers/plans/2026-10-21-public-source-release.md.

Completed: source recovered by cloning existing repository; original v8.3.5 ZIP recovered and byte-matched against all 75 source payload files; 154 files/301 history blobs scanned for common secrets/private paths, no candidates. Desktop and original ZIP tests 71 each passed. Original ZIP SHA256: 178076bb54eff3d8a01d882d23a7e413be5a8aec00fc150500aaab1f58f2802c.

Next: portable offline tests, GPL distribution metadata, test/build verification, main integration, Windows CI prerelease publication. Do not reset/reinitialize/delete caches. Re-read this file and inspect git status/log before resuming. No real market coverage or manual Windows testing claimed.

## Stage 2 — verified packaging and portable tests

- Original baseline v7.6.3 recovered; SHA256 dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e; its 63 tests pass through the audit test.
- Initial 38-row test failure isolated: AKShare fallback reached real network and returned190 rows. Test now supplies short controlled rows to every fallback; no production strategy or transport code changed.
- Full local suite with explicit legacy artifact: 228 passed. Original desktop71 passed. Licensed ZIP independently extracted:71 passed;79 files (75 original +4 legal/build/source documents).
- Licensed ZIP SHA256 610f2ae17d3a5765d020cff608f04dbbbe7b59cc5f0dfc50ff46500bc7192c43. Native Qt window construction passed on Linux offscreen; Windows CI pending.
- First remote checkpoint b901feaae395b66346aa75c358e1799a0bf9d411, branch codex/v8-phase1. Native git push has no credentials; GitHub Git-data API is the authorized push path.
- Next: review/commit/sync new packaging and docs, integrate full source tree into main preserving README/LICENSE, execute Windows gated prerelease workflow. Release is not published yet. Do not repeat already completed tests unless code changes or a failed check warrants it.

## Pre-publication review

Independent read-only review confirmed all75 program file hashes unchanged. One important issue found: gh release create --target does not retarget an existing tag. Added ensure_release_tag.py to reject mismatched existing tags, create missing tags at the tested full SHA and resolve them again; publication uses --verify-tag. Four focused tests first failed then passed. No program files changed.
