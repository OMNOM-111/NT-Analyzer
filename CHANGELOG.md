# Changelog

## 2026-06-26

- Fixed position sizing in three strategy engines so a trade is skipped when
  one contract exceeds the configured per-trade risk budget after costs.
- Added concrete-class entry signals and legacy signal attribution for C007,
  C127, and the geodesic research pilot.
- Corrected AI Strategy Lab risk guidance and added static gates against
  anonymous entry signals and forced minimum-one-contract sizing.
- Added regression coverage for the June 25 C007/C127 attribution incident and
  repository-wide NinjaTrader strategy safety checks.

## 2026-06-25

- Added product-level repository documentation and proprietary license.
- Added CI workflow for Python suite and conditional local bridge build.
- Documented Git hygiene boundaries for runtime, research, and AI Lab data.
- Prepared AI Strategy Lab source, UI, schema, prompt, and reference assets for
  controlled product commits while keeping generated model/runtime artifacts
  local.
