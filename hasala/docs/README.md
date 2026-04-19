# Ethmac Workspace — Step-by-step setup log

This folder contains one numbered document per setup/execution step. Every
terminal command run during setup is reproduced here verbatim. These
documents ship with the final competition submission under the team's
`README.md` → "Reproducibility" section.

| Doc                             | Purpose                                     | Status |
| ------------------------------- | ------------------------------------------- | ------ |
| `00_workspace_setup.md`         | Create directory layout                     | done   |
| `01_toolchain_verification.md`  | Confirm yosys / OpenSTA / iverilog versions | done   |
| `02_clone_ethmac.md`            | Clone FreeCores ethmac @ commit dd26899…    | done   |
| `03_golden_ppa_baseline.md`     | Run `run_ppa.sh` on pristine RTL, capture baseline | done |
| `03_golden_ppa_run.log`         | Full stdout/stderr of the golden PPA run    | artifact |
| `04_base_testbench.md`          | iverilog full-TB run of `bench/verilog/`    | done (50/50 pass, 0 fail) |
| `05_smoke_tb_and_pipeline_scaffold.md` | Fast smoke TB + agentic pipeline    | pending |
| ...                             | (later steps added as work progresses)      |        |

Conventions:
- Each doc begins with a **Date** and **Goal** line.
- The full shell command block comes first, then observed output, then any
  interpretation or decisions.
- Binary / large artifacts (netlists, PPA logs) are stored alongside but
  never inlined into the markdown.
