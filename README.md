# reviewer2

Adversarial peer review for academic PDFs.

`reviewer2` is a fork of the open-source pipeline behind
[isitcredible.com](https://isitcredible.com/) by
[The Catalogue of Errors Ltd](https://github.com/isitcredible/reviewer2).
The original design and all prompt engineering are their work. This fork
replaces the hard Google Gemini dependency with a provider-agnostic backend
built on the OpenAI SDK, so the same pipeline can run against Ollama Cloud,
OpenAI, or any OpenAI-compatible endpoint.

The pipeline produces a plain-text critical review of a PDF manuscript
through a 30+ stage chain of LLM calls. The chain is built around one
idea: aggressive prompting is what gets a language model to read a paper
carefully, and a verification cascade is what removes the hallucinations
aggression produces.

The design is described in *Yell at It: Prompt Engineering for Automated
Peer Review* ([`paper/yellatit.pdf`](paper/yellatit.pdf)).

**Version:** 1.0.1

---

## What changed from the original

| Area | Original | This fork |
|------|----------|-----------|
| LLM backend | Google Gemini SDK (hard dep) | OpenAI SDK with configurable `base_url` |
| Default provider | Gemini | Ollama Cloud (`kimi-k2.5:cloud`) |
| PDF ingestion | Native Gemini file upload | [docling](https://github.com/DS4SD/docling) PDF-to-markdown (optional, graceful fallback) |
| Config | `GEMINI_API_KEY` env var only | `reviewer2.yaml` + env vars + CLI flags |
| Literature search | Google Search tool (Gemini-native) | [RAiner](https://github.com/CasparDP/RAiner) vector search (optional) |
| Dependencies | `google-genai`, reportlab | `openai`, `pydantic`, `pyyaml`, `python-dotenv` |

---

## Requirements

- Python 3.10+
- An API key for your chosen provider (Ollama Cloud, OpenAI, etc.)
- `qpdf` on `PATH` for PDF preprocessing
- (Optional) [docling](https://github.com/DS4SD/docling) for PDF-to-markdown conversion
- (Optional) [RAiner](https://github.com/CasparDP/RAiner) for literature search enrichment
- (Optional) A Mathpix account for the math-audit add-on

---

## Install

Clone and install for development with Poetry:

```bash
git clone https://github.com/CasparDP/reviewer2
cd reviewer2
poetry install
```

Or with pip:

```bash
pip install -e .
```

---

## Setup

Copy the environment template and fill in your API key:

```bash
cp .env.example .env
# edit .env: set REVIEWER2_API_KEY=your-key-here
```

The `.env` file is loaded automatically and is gitignored. No `export`
needed.

**Optional: docling** (enables proper PDF-to-markdown conversion; the
pipeline works without it but LLM stages receive no PDF text):

```bash
pip install docling
```

**Optional: RAiner** (enables literature search enrichment in stages 00a
and 03b):

```bash
pip install -e /path/to/RAiner
```

---

## Quickstart

```bash
# Default run (Ollama Cloud, kimi-k2.5:cloud)
poetry run reviewer2 paper.pdf -o report.txt

# Cheapest smoke test: base review only, outputs kept for inspection
poetry run reviewer2 paper.pdf -o report.txt --base --work-dir ./run --keep-work-dir

# OpenAI
poetry run reviewer2 paper.pdf -o report.txt \
  --base-url https://api.openai.com/v1 \
  --model gpt-4o
```

A default run takes 15 to 45 minutes with Gemini Flash/Pro. With a large
model via Ollama Cloud (e.g. `kimi-k2.5:cloud`) expect 2 to 4 hours —
the pipeline makes 30+ sequential API calls and throughput is governed by
the provider's generation speed. Use `--base` for the cheapest and fastest
run while testing. The math and code audits are opt-in.

---

## Input files

- **Main PDF** — the positional argument; always required.

- **Supplementary PDFs** — `--supp PATH` (repeatable). Merged after the
  main paper and visible to every stage except the math Proofreader.

  ```bash
  reviewer2 paper.pdf --supp appendix.pdf --supp online_appendix.pdf
  ```

- **Replication-code directory** — `--code-dir PATH`. Source files are
  compiled into a single PDF and attached behind the paper for the
  code-audit stages.

  ```bash
  reviewer2 paper.pdf --code-dir ./replication/
  ```

A volume circuit breaker halts the run if the combined page count exceeds
500 pages. Override with `--skip-size-check`.

---

## What the report contains

- **Is It Credible?** A short essay (up to 700 words) answering the
  titular question.
- **The Bottom Line.** Three to five sentences on whether the paper's
  contributions hold.
- **Potential Issues.** A verified, categorised list of problems found
  during review.
- **Future Research.** Constructive proposals that follow from the
  critique.

With the copyedit and editor's-note stages enabled (the default), the
report also carries an author-facing editor's note with revision advice.

---

## How it works

Each stage is a prompt in `prompts/`; outputs land as `.txt` files in a
working directory and are chained together. A run is resumable by pointing
`--work-dir` at an existing folder.

### 1. Red Team: five adversarial agents

- **The Breaker** targets intellectual foundations: whether the theoretical
  framework predetermines the findings, whether disputed premises are
  treated as obvious, whether causal design labels are earned rather than
  merely claimed.
- **The Butcher** dissects the empirical machinery: whether the method can
  answer the question, whether measures capture the theoretical constructs,
  whether robustness checks threaten anything.
- **The Shredder** audits procedural claims against documentation: whether
  sample sizes cohere across methods, results and tables; whether
  pre-registration claims match reported outcomes.
- **The Collector** returns to every location the Butcher and Shredder
  flagged and picks up what the attackers missed.
- **The Void** catalogues what the paper does not say: unmeasured
  confounds, reverse causation, selection bias, alternative explanations
  the authors never tested.

For non-empirical papers, the Butcher and Shredder are replaced by a
second Breaker pass that probes theoretical and mathematical arguments more
aggressively.

### 2. Filtering: Blue Team and verification

- **The Blue Team** argues the paper's defence.
- **The Assessment** stage rules on each finding.
- **The Fact Checker** and **External Check** confirm page numbers,
  quotations and equations against the PDF, and audit citations of outside
  sources.
- **Review Checker**, **Citation Verifier** and **Reviser** apply the same
  discipline to the assembled review.

### 3. Writing

- **The Reviewer** drafts the credibility assessment from the verified
  issues list.
- **The Legal pass** removes defamatory or legally risky phrasing.
- **The Formatter** cleans up structure and markdown.
- *(Optional, on by default.)* **The Alchemist**, **Polisher**,
  **Proofreader** and **Copy-Editor** produce the author-facing revision
  advice.

---

## Add-ons

| Flag | Default | What it does |
|------|---------|--------------|
| `--math` | off | Math audit. Four stages re-derive key results, check text-to-equation consistency, and consolidate via an independent sober re-check on MathPix OCR text. Requires `MATHPIX_APP_ID` and `MATHPIX_APP_KEY`. |
| `--code-dir PATH` | off | Replication-code audit. Three agents examine the code (Divergence Hunter, Bug Hunter, Data Archaeologist), followed by a verification pass. |
| `--no-copyedit` | (on) | Skip the copyedit stages. |
| `--no-editor-note` | (on) | Skip the editor's-note stage. Disabling either copyedit or editor's note skips all Writer-Mode stages. |
| `--base` | off | Core review only. Cheapest run. |

---

## Configuration

### Provider and model

Settings are resolved in this order (later wins): built-in defaults →
`reviewer2.yaml` → `.env` → environment variables → CLI flags.

**CLI flags:**

| Flag | Purpose |
|------|---------|
| `--model MODEL` | Set both fast and strong tiers to MODEL |
| `--fast-model MODEL` | Override the fast tier (metadata, formatting stages) |
| `--strong-model MODEL` | Override the strong tier (breaker, reviewer, math stages) |
| `--base-url URL` | Override the provider base URL |
| `--config PATH` | Path to a `reviewer2.yaml` config file |

**Environment variables:**

| Variable | Purpose |
|----------|---------|
| `REVIEWER2_API_KEY` | API key for your LLM provider |
| `REVIEWER2_BASE_URL` | Provider base URL |
| `REVIEWER2_FAST_MODEL` | Fast-tier model name |
| `REVIEWER2_STRONG_MODEL` | Strong-tier model name |
| `MATHPIX_APP_ID` | Mathpix app ID (only with `--math`) |
| `MATHPIX_APP_KEY` | Mathpix app key (only with `--math`) |

**`reviewer2.yaml`** (optional, place in working directory or
`~/.config/reviewer2/config.yaml`):

```yaml
provider:
  base_url: https://ollama.com/v1
  fast_model: kimi-k2.5:cloud
  strong_model: kimi-k2.5:cloud
  temperature: 0.1
```

### Provider examples

```bash
# Ollama Cloud (default)
REVIEWER2_API_KEY=your-ollama-key reviewer2 paper.pdf

# OpenAI
reviewer2 paper.pdf --base-url https://api.openai.com/v1 --model gpt-4o

# Any OpenAI-compatible endpoint
reviewer2 paper.pdf --base-url https://your-endpoint/v1 --model your-model
```

---

## RAiner integration

If [RAiner](https://github.com/CasparDP/RAiner) is installed, stages 00a
and 03b will search your personal paper library and inject relevant results
into the prompt. This gives the pipeline access to literature context
beyond what is cited in the paper under review.

RAiner is not listed as a package dependency because it requires its own
database setup. Install it as a local editable package:

```bash
pip install -e /path/to/RAiner
```

The pipeline degrades gracefully if RAiner is absent.

---

## Resumability

Every stage output is written to `--work-dir` as a `.txt` file. If a run
fails or is interrupted, re-run with the same `--work-dir` and the pipeline
picks up where it stopped.

---

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

The pipeline and prompts in this repository are the result of many months
of empirical tuning by The Catalogue of Errors Ltd. The names
"Reviewer 2", "isitcredible.com", and "The Catalogue of Errors" are
trademarks and are not licensed under Apache 2.0. Forks must use a
different name.
