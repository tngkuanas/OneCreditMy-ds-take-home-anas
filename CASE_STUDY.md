# Company summaries for supplier screening

## What a good summary is for this team, and why

The summary should help a reviewer decide what to investigate next. It should not make the supplier decision for them.

I prioritised factual accuracy over fluent writing. A paragraph that confuses profit with cash, or a court claim with a proven debt, would make the review worse. My criteria are:

- Explain what the company does and its recorded status.
- Describe revenue and profit trends with the relevant years, without hiding important interim losses.
- Distinguish accounting profit from operating and free cash flow.
- Preserve missing accounts, audit exceptions, negative equity, funding gaps and material litigation.
- Include useful ownership or director context without inventing governance concerns.
- End with a practical follow-up grounded in the record.

The target is a short first read, normally 100–150 words. I allow shorter summaries when additional detail adds little, especially when the source is sparse. Critical facts take precedence over length; if they exceed 150 words, the output fails acceptance rather than silently losing a warning.

I avoided a risk score. There are no supplier outcomes, contract sizes, sector benchmarks or agreed thresholds in the data. A score would look precise without having a defensible meaning.

## What you built

The final version is **v4**, covering **all 50 companies**. It uses Python and **qwen3.5:9b through the local Ollama HTTP API**. The model was already installed, which avoided hosted API keys and quotas. This is a local API rather than one of the hosted free-tier providers suggested in the brief.

The pipeline has three steps:

1. Python builds a catalog of facts, performs arithmetic and attaches source paths to each sentence.
2. The model chooses up to two optional fact IDs. Its JSON schema lists only the optional IDs available for that company; it cannot write the paragraph or invent figures.
3. Python preserves required information, fits optional details into the remaining word budget, and renders short paragraphs with a follow-up question.

The submitted output is `summaries/v4.jsonl`. The viewer shows it beside v3 and lets the reviewer expand the evidence. `v4-rules.jsonl` uses the same facts and wording but selects optional details with contextual rules, allowing a direct comparison with the LLM selector.

### What changed during development

**v1:** Asking for the whole paragraph was easy, but unreliable. On SYN-000029 it produced 207 words, described five shareholder-directors when the record lists four shareholders, and raised an unsupported audit independence concern.

**v2:** A tighter prompt corrected the shareholder count but still produced 206 words, repeated the audit concern and rounded -RM 8,059 to a loss of RM 9k. The saved responses and source-comparison findings remain in the repository.

**v3:** I restricted the model to choosing verified facts. This controlled the wording and figures, but summaries were repetitive and largely listed numbers. The outputs differed from a simple rules-only comparison for only 4/50 companies.

**v4:** I added explicit rising/falling trends and separated business context, financials, concerns and the next check into short paragraphs. Majority corporate ownership is preserved, and recent director appointments are counted against the record date. When most listed directors were appointed during 2025, that fact is retained regardless of model selection; it gives context on the current board, not a governance risk label. An interim loss between profitable endpoint years is also required information. Ownership snapshots are not described as ownership changes; appointment dates are not treated as evidence of turnover or misconduct.

The first v4 trial rejected **5/50** model selections because they included IDs that were not available as optional facts. The summaries still retained required information, but the run failed acceptance. I then constrained the generation schema itself to available IDs. The trial is saved in `evaluations/v4-selection-trial.json`, including links to the original responses.

### Reproduction

The model uses temperature 0, seed 42, thinking disabled and an 8,192-token context. These settings do not guarantee identical output across hardware or model updates. The installed model digest and Q4_K_M quantisation are recorded in `evaluations/environment.json`.

Every response is saved under `runs/`. Cache keys include the facts, prompt, model name, schema and settings. A one-company refresh preserves other saved companies. Summary and evidence exports are committed through one authoritative snapshot after generation completes. Ordinary write failures restore the previous exports; after a hard interruption the viewer can still read the previous complete snapshot, while evaluation rejects inconsistent exports. The final system adds no libraries beyond the supplied environment.

Run `just serve` to inspect saved outputs and `just check` to reproduce checks without calling a model. `just generate` is optional and uses the local API. Observed request times and token counts are reported in [evaluations/RESULTS.md](evaluations/RESULTS.md); they are not estimates of total development time. There are no billed generation API calls, although local compute is not cost-free.

## How you know whether it's good

I separate factual checks, scenario coverage and actual reader usefulness. The first two can be tested here. The third still needs people.

### Source checks across the supplied companies

The evaluator reads the original records separately from the renderer. It verifies status, years, required amounts, audit exceptions, legal roles, pending-claim totals, optional figures, source paths, coverage and length.

The stronger checks bind amounts to named fields and years. Swapping the first and last revenue figures cannot pass merely because both numbers still appear somewhere in the paragraph. Other checks detect incorrect trend directions, invented extra currency amounts, missing interim losses and appointment counts that include dates after the record date.

All **50/50** final summaries pass acceptance, with **1,386/1,386** applicable automated checks passing. The median length is **104.5 words**, with a range of **52–134**; **34/50** fall within the original 100–150 word target. The others are shorter, rather than padded with optional detail. Per-company results are saved in `v4-report.json` and the results report. Basic source profiling also checks 508 statement identities; all agree within RM 1. There are 101 null ratio values, which remain unavailable rather than being treated as zero. These are limited integrity checks, not an audit of every ratio definition.

An adversarial review found gaps in the original checks: swapped single-year revenue/profit, an invented audit opinion, and an incorrect petition count could pass when the evidence repeated the same error. Those cases now fail the complete acceptance command, even with matching summary/evidence files. Audit opinions and litigation counts are checked against the source, and single-year amounts are bound to their fields and year. The viewer also binds check results to the exact summary/evidence revision, rather than displaying stale green results after an update.

The same review identified a content omission: SYN-000282's profit was higher than FY2022, but had fallen from RM 2,026,448 in FY2023 to RM 1,865,751 in FY2024. The latest-year reversal is now required information, as it is for the five other supplied companies whose latest direction conflicts with the endpoint comparison. This illustrates why passing a large number of checks is not sufficient evidence on its own.

### Development cases and additional stress cases

The original 12-company challenge set covers missing accounts, single-year data, losses, negative equity, older audit warnings, winding-up status and different litigation roles. For example:

- SYN-000217 must retain its FY2023 disclaimer despite a clean FY2024 opinion.
- SYN-000286 has RM 466,500 in pending defendant claims, not proven liabilities, and a pending winding-up petition.
- SYN-000545 is winding up despite positive reported profit; its status and historical going-concern warning must remain visible.

I also generated **24 additional synthetic stress cases** using a fixed seed. They test interim losses, foreign corporate ownership, date boundaries, zero revenue, null ratios and legal roles. v4 passes **24/24** specified cases; v3 passes **12/24** against these expanded requirements. Some differences reflect newly required context and explicit trend wording, so this is not an estimate of v3's factual accuracy.

These tests exercise the fact builder and renderer with explicit fact requests; they do not measure the model's prioritisation on unseen records. The records are synthetic perturbations of the supplied schema, not independently sourced companies or a held-out real-world test set. Once inspected, they are regression cases. I do not claim statistical generalisation from them.

The automated tests also deliberately corrupt outputs: they swap figures, change years or directions, alter ownership percentages, remove audit warnings and promote claims into liabilities. Cache, partial-update and interrupted-run tests cover operational failures as well as summary content.

### Human evaluation is prepared, not completed

`evaluations/REVIEW_PACKET.md` contains 16 shuffled A/B pairs. Eight compare v3 with v4; eight compare v4 with ranked rules to isolate the model's role. Reviewers can inspect source records and record factual errors, omissions, clarity, preferences and time spent. Version assignments are kept in a separate key.

The shipped ratings are blank. The reporting code counts actual entered preferences, not model-generated ratings. This is a practical way to collect feedback, but it is not completed human evaluation or a double-blind study.

Passing the automated checks does not prove that every important fact was selected or that a reviewer makes better decisions. The evaluator and renderer share a task definition, even though their checks are implemented separately. v4 differs from its ranked-rules comparison for **48/50** companies, largely because the model selects less optional detail, but different selections do not establish added value. The ranked rules remain a credible simpler alternative.

## What you'd do next, and how you'd keep improving it

The next step is to collect the prepared human ratings. I would agree what matters with the supplier-review team first, then compare factual errors, important omissions, clarity, review time and preferences. A tie is a valid result. If the model does not improve relevance or save time, I would keep the ranked rules rather than retain an inference cost without evidence of benefit.

I would then add contract context, such as the size and type of the proposed engagement. That would make prioritisation more useful without pretending that a single threshold applies to every industry or supplier.

For continued improvement, I would retain the regression cases, add reviewed failures, and reserve genuinely new records before tuning the next version. In operation I would monitor source freshness, missing fields, rejected selections, failed checks and reviewer corrections. Aggregated litigation and fixed sentence wording remain limitations; the full records should stay available alongside the summary.

This is a reproducible screening prototype, not a calibrated credit model or a production supplier-approval system.

**AI assistance:** Codex assisted with implementation, prompts, source comparisons, tests, experiments, documentation and drafting this case study. The local Qwen model generated v1/v2 and selected optional facts for v3/v4. No independent human evaluation is claimed. The code, examples and decisions should be understood before the work is submitted or presented.
