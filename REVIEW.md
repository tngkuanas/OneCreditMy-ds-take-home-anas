# Final iterative review

Scope: the supplied 50 records; the supported company schema and controlled summary
fact catalog; generation and retry commands; saved-output evaluation; snapshot
publication and recovery; viewer APIs and JavaScript syntax; review-data handling;
reproducibility of committed artifacts and submission documentation.

## Passes completed

1. Reviewed source-to-summary calculations, field/year bindings, audit opinions,
   litigation roles and counts, evidence paths, source freshness, and recent-year
   reversals. Retained the earlier adversarial regressions and added source-derived
   value checks for every supported fact, including optional interim figures.
2. Reviewed failure and recovery paths. Fixed successful CLI exits after rejected
   selections and preserved malformed HTTP response bytes for explicit retry.
   Source loading now shares the viewer schema and rejects duplicate company IDs,
   unsupported case roles/statuses, invalid percentages, non-finite values and
   duplicate or unsupported financial-year collections before generation.
3. Reviewed review-packet integrity and input measurements. Partial feedback keeps
   the original packet fixed; invalid ratings, negative/non-finite timings and
   malformed annotations are rejected. Other inactive company statuses no longer
   imply winding-up status.
4. Ran a clean pass over all saved complete versions and their source/output
   fingerprints, all producer fact types across the supplied and synthetic cases,
   and byte-identical cached replay with API calls prohibited. No further
   substantive reproducible finding remained in this reviewed scope.

## Final local evidence

- 73 automated regression tests pass, including the actual previously reproduced
  failures rather than only successful examples.
- v4 covers 50/50 companies and passes 1,586 applicable acceptance checks.
- The original 12 challenge cases and 24 additional renderer stress cases pass.
- Ruff, formatting, strict viewer type checking and JavaScript syntax checks pass.
- Saved summaries can be replayed without model calls and without changing bytes.
- CI runs evaluation/report regeneration and rejects uncommitted changes to
  generated summaries or evaluation artifacts, guarding against stale results.

## Limits of the conclusion

This is an AI-assisted engineering review, not an independent human assessment or
a guarantee that no defect exists. The wording/value contracts verify this
controlled renderer; they are not a general evaluator for arbitrary LLM prose.
Changes to supported fact formats require deliberate contract changes.

Reader preference and review-time improvements remain unmeasured. The prepared
human ratings are blank. The 24 new cases are synthetic regression cases, not a
held-out real-company study. The model's advantage over ranked rules is unproven.

Generation assumes one writer, as documented; concurrent generation and production
deployment are outside this review. Snapshot tests cover ordinary write failures
and hard process interruption, not every possible hardware or filesystem failure.
Browser visual review was unavailable because the browser access host could not be
reached; viewer APIs, source/output revision checks and JavaScript syntax were
verified instead. The original assessment brief is preserved in README.md.
