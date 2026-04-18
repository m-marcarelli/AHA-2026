# HOST AI Hardware Attack (AHA!) Challenge: Scoring & Evaluation Rubric

This document outlines the scoring criteria for the HOST AI Hardware Attack (AHA!) competition. The scoring is divided into core technical execution, vulnerability severity, physical stealth, and detection analytics.

Teams will be evaluated on a 4-point scale for each metric:
* **4 - Exemplary:** Exceeds expectations, highly innovative, flawless execution.
* **3 - Proficient:** Meets expectations, solid technical execution, minor flaws.
* **2 - Developing:** Partially meets expectations, functional but lacks polish.
* **1 - Novice:** Fails to meet expectations, incomplete, or requires manual intervention.

---

## Part 1: AI Utilization, Automation & Documentation (Phase 1)

This section evaluates the team's engineering pipeline, how effectively they utilized generative AI, and the quality of their documentation.

* **Creative Use of Generative AI:** Evaluates the sophistication of the AI pipeline (e.g., complex prompt chaining and engineering, RAG, agentic workflows, etc.) versus basic copy-pasting.
* **System Automation:** Measures the end-to-end automation of the generation, insertion, and testing pipeline.
* **Exploitation Simulation:** Assesses the quality of the testbench in proving both normal operation and the successful Trojan exploit.
* **Documentation & Reproducibility:** Evaluates the clarity of the team's write-up, full AI logs, and instructions for replicating the exploit/using the generative AI framework.

| Evaluation Criteria | 4 - Exemplary | 3 - Proficient | 2 - Developing | 1 - Novice |
| :--- | :--- | :--- | :--- | :--- |
| **Generative AI Use** | Dynamic, seamless AI generation and insertion using advanced techniques (e.g., AST manipulation). | Effective AI generation of logic, but relies on little more than prompt engineering and basic insertion. | Simple AI generated logic, but required significant manual editing through repeated prompting. | Minimal AI use; just simple prompting with copy-pasting. |
| **System Automation** | Fully automated, "one-click" pipeline from AI generation to simulation output. | Highly automated but requires 1-2 manual steps (e.g., moving files). | Fragmented pipeline requiring manual oversight and handoffs between scripts. | No automation; entirely manual generation, insertion, and testing. |
| **Simulation Quality** | Flawless testbench; explicitly proves normal operation *and* the payload trigger with clear waveforms. | Clearly demonstrates payload triggering, but proof of normal operation is lacking. | Buggy or hard to interpret; proves payload works but trigger mechanism is unclear. | Missing, fails to compile, or does not successfully demonstrate the exploit. |
| **Documentation** | Exceptional detail on AI prompts, architecture, and perfect reproducibility steps. | Clear and complete explanation of strategy and mechanism; mostly reproducible. | Basic overview lacking pipeline details; reproducibility requires guesswork. | Missing or highly confusing; fails to explain AI usage or Trojan operation. |

---
## Part 2: Vulnerability Severity & Physical Stealth (Phase 1)

This section evaluates the actual hardware vulnerabilities inserted by the AI, scoring it on reported [CVSS score](https://nvd.nist.gov/vuln-metrics/cvss/v3-calculator) and its physical footprint (PPA).


* **Standard CVSS (Average Severity):** Evaluates the threat level of the Trojans using the standard Common Vulnerability Scoring System (CVSS) Base Score (0.0 to 10.0). Teams will self-assess (and judges will verify) the CVSS score for each Trojan based on its Attack Vector, Attack Complexity, and CIA (Confidentiality, Integrity, Availability) impact. The team's final score for this metric is the average of these Base Scores.
* **PPA Overhead (Stealth):** Evaluates the Power, Performance (Timing), and Area overhead introduced by the Trojan compared to a clean "golden" baseline. The smaller the footprint, the higher the score. **More details about how teams can calculate this will be provided when the challenge releases.**

| Evaluation Criteria | 4 - Exemplary | 3 - Proficient | 2 - Developing | 1 - Novice |
| :--- | :--- | :--- | :--- | :--- |
| **Standard CVSS Score (Average)** | **Average CVSS: 7.0 – 10.0 (High/Critical)**<br>Trojans consistently demonstrate severe impact (e.g., total system compromise) and highly accessible attack vectors (e.g., Network/Adjacent). | **Average CVSS: 4.0 – 6.9 (Medium)**<br>Trojans have moderate impact or require more restricted attack vectors (e.g., Local/Physical access) to exploit successfully. | **Average CVSS: 0.1 – 3.9 (Low)**<br>Trojans have minimal impact, extremely high attack complexity, or are very difficult to trigger reliably. | **Average CVSS: 0.0**<br>Trojans do not qualify as exploitable vulnerabilities, or the team failed to insert functional payloads. |
| **PPA Overhead (Stealth)** | < 1% average deviation from golden baseline in Area, Power, and Timing across all inserted Trojans. | 1% to 5% average deviation from golden baseline across all inserted Trojans. | 5% to 10% average deviation from golden baseline across all inserted Trojans. | > 10% average deviation, or the Trojans frequently cause synthesis/compilation to fail. |

---

## Part 3: CTF Combat Scoring (Phase 2)

This section governs the primary "Attack/Defense" phase of the competition. Teams earn points both offensively (detecting other teams' Trojans) and defensively (evading detection by other teams). 

To encourage sophisticated exploits and advanced detection techniques, this phase utilizes a **Dynamic Scoring Model**. Rather than awarding flat points, the value of each Trojan scales dynamically based on its stealth and how many teams successfully find it.

### 1. Offensive Scoring (Detecting Trojans)
When a team successfully detects a Trojan inserted by another team, they are awarded points from a shared "bounty pool" dedicated to that specific Trojan.

* **Commonly Discovered Trojans (Low Reward):** If a Trojan is easily detected and found by many teams, the bounty pool is split among all of them. This results in **fewer points** awarded to each discovering team.
* **Rarely Discovered Trojans (High Reward):** If a team's AI detection pipeline catches a highly sophisticated Trojan that most other teams missed, the pool is split among far fewer teams. This results in **significantly more points** for the discoverers. 

### 2. Defensive Scoring (Hiding Trojans)
Teams are also awarded points based on the survivability and stealth of their submitted Trojans. A Trojan's defensive score is directly tied to how many opposing teams *failed* to detect it.

* **Commonly Discovered Trojans (Low Reward):** If a team's inserted Trojan is easily found by the majority of the competition's detection pipelines, the inserting team receives **fewer points**. This penalizes obvious, poorly integrated vulnerabilities.
* **Rarely Discovered Trojans (High Reward):** If a team designs a Trojan so effectively that very few (or no) opponent AI systems manage to detect it, the inserting team retains **maximum points** for their stealth.

### Dynamic Scoring Guidelines & Implementation

To implement this mathematically, we will use a standard CTF dynamic point formula. Assume every inserted Trojan has a base **Maximum Point Value (e.g., 1000 points)**.

* **Offensive Point Formula:** For any given Trojan, the Offensive Points awarded to each successful detecting team = 
  `(Maximum Point Value) / (Number of Teams that Detected It)`
  *(Example: If 10 teams find a 1000-point Trojan, they each get 100 points. If only 1 team finds it, they get all 1000 points.)*

* **Defensive Point Formula:** The Defensive Points awarded to the team that inserted the Trojan = 
  `(Maximum Point Value) * (Number of Teams that FAILED to Detect It / Total Number of Opposing Teams)`
  *(Example: If there are 10 opposing teams, and 8 fail to find it, the inserter gets 800 points. If everyone finds it, the inserter gets 0 points.)*

**Important Rule:** If an inserted Trojan causes the host open-source hardware project to fail its standard functional testbench (i.e., the Trojan inadvertently breaks the base functionality of the device), it is disqualified. The inserting team receives **0 defensive points**, as the Trojan is considered non-viable, regardless of whether opposing teams detected it or not.

---

## Part 4: Advanced Detection Analytics (Phase 2)

This section moves beyond basic CTF points and evaluates the precision and analytical power of a team's AI-driven detection systems.

* **False Positive Resilience:** Evaluates how well the detection AI handles completely clean designs without hallucinating vulnerabilities.
* **Explainability & Localization:** Evaluates whether the AI simply guesses "infected" or actually pinpoints the exact malicious logic.
* **Documentation of Detection Framework:**  Evaluates the clarity of the team's write-up, full AI logs, and instructions for the design and use of their vulnerability detection framework.

| Evaluation Criteria | 4 - Exemplary | 3 - Proficient | 2 - Developing | 1 - Novice |
| :--- | :--- | :--- | :--- | :--- |
| **False Positive Resilience** | AI correctly identifies all clean designs; 0% false positive rate. | Occasional hallucinations; < 10% false positive rate on clean designs. | Frequent hallucinations; 10% to 30% false positive rate. | Overly aggressive AI; > 30% false positive rate (flags almost everything). |
| **Localization & Explainability** | Pinpoints exact gate-level coordinates, AST nodes, or specific lines of malicious code. | Identifies the general module or hierarchical path containing the Trojan. | Outputs a binary "True/False" for infection with a vague explanation. | Outputs "True/False" with no explanation, or hallucinated reasoning. |
| **Documentation** | Exceptional detail on AI prompts, architecture, and perfect reproducibility steps. | Clear and complete explanation of strategy and mechanism; mostly reproducible. | Basic overview lacking pipeline details; reproducibility requires guesswork. | Missing or highly confusing; fails to explain AI usage or Trojan detection methods. |


