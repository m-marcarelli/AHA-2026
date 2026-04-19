# Prompts

Every prompt the pipeline sends to an LLM, version-controlled as
plain text. The orchestrator code references these by filename; the
files here are the canonical source. Editing a prompt without
updating the corresponding orchestrator call site is the maintenance
hazard — `tests/test_prompts.py` checks that every referenced file
exists.

| File                          | Stage / model                 | Purpose                                                          |
|-------------------------------|-------------------------------|------------------------------------------------------------------|
| `00_system_security.md`       | system, all calls             | Authorised-research framing for every LLM call                   |
| `01_ideation_propose.md`      | Stage 0, parallel reviewers   | Each model independently proposes a trojan concept               |
| `02_ideation_select.md`       | Stage 0b, Opus judge          | Pick three distinct CIA-leg specs from the proposals             |
| `03_generate_patch.md`        | Stage 2, Sonnet best-of-N     | Emit the 4-field patch JSON for the legacy single-flop template  |
| `04_generate_tb.md`           | Stage 2, Sonnet               | Emit the per-trojan testbench (with VCD dump on)                 |
| `05_repair_patch.md`          | Stage 3 repair                | Fix RTL given simulator stderr                                   |
| `06_repair_tb.md`             | Stage 3 repair                | Fix testbench given simulator stderr                             |
| `07_blue_team_review.md`      | Stage 4b legacy               | Whole-file blue-team review (kept for fallback)                  |
| `07b_blue_team_diff.md`       | Stage 4b new                  | Diff-aware ensemble blue-team review                             |
| `08_stealth_harden.md`        | Stage 4b harden               | Identifier rename + constant restructure                         |
| `09_cvss_score.md`            | Stage 4c                      | Pick CVSS 3.1 vector letters (score is computed deterministically)|
| `10_score_optimizer.md`       | Stage 6                       | Final review against competition rubric                          |
| `11_readme_gen.md`            | Stage 6                       | Submission README composition                                    |
| `12_patch_select.md`          | Stage 2 best-of-N             | Cross-model judge picks the stealthier of two patches            |

The prompts are intentionally explicit about the IEEE HOST 2026 AHA
Challenge context — the pipeline only operates against authorised
academic targets.
