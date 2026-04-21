# reviewer2 — project notes

## Running the pipeline from Claude Code

**Before invoking `reviewer2` on a real paper, confirm with the user.** A
default run takes 15–45 minutes and costs a few dollars in Gemini API
usage. That is not a routine command to fire off autonomously.

Entry point:

```bash
reviewer2 paper.pdf -o report.txt
```

Requires `GEMINI_API_KEY` in the environment and `qpdf` on `PATH`. Install
for development with `pip install -e .` from the repo root.

Because runs are long, start them with `run_in_background: true` rather
than foreground. Outputs stream to the working directory (default: a temp
dir, override with `--work-dir`); the run is resumable by pointing
`--work-dir` at the same folder.

Flags worth knowing: `--math` needs `MATHPIX_APP_ID` and
`MATHPIX_APP_KEY`; `--code-dir PATH` enables the replication-code audit;
`--base` disables all add-ons for the cheapest real run; the 500-page
volume circuit breaker is overridden with `--skip-size-check`.

## Versioning

Semver. When bumping the version, update **all three** in lockstep:

- `pyproject.toml` (`version = "..."`)
- `src/reviewer2/__init__.py` (`__version__ = "..."`)
- `README.md` (the `**Version:**` line)

These drifted apart between the initial commit and v1.0.1 (pyproject was at
1.0.0 while `__init__.py` was still at 0.1.0). Grep for the old version
before committing to catch any that were missed.

Tag as `vX.Y.Z` after the release commit, then `git push && git push --tags`.

Bump size is a judgment call, not a mechanical rule. A change that technically
alters a default but has no real dependents yet is a patch, not a minor.
Breaking changes in the OSS port → `v2.0.0` (the README promises this).

## v2 migration: model-agnostic LLM backend

**Status:** planned, not yet started.

**Goal:** Replace the hard Gemini dependency with a provider-agnostic backend
using the OpenAI SDK. Default to Ollama Cloud. Keep Gemini (and any other
provider) as a `base_url` swap.

**Why:** Privacy (Ollama's no-data-retention claim), cost (free tier +
subscription), model freedom (kimi-k2.5, glm-5, etc.), and portability.

### Architecture

OpenAI SDK with configurable `base_url`. One client, swap the URL per provider:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("REVIEWER2_API_KEY"),
    base_url="https://api.ollama.com/v1",
)
```

This is the same pattern used in RAiner for OpenRouter
(`RAiner/rainer/agent.py`, lines 302-309).

### Config design (YAML + env vars, following RAiner's pattern)

```yaml
provider:
  base_url: https://api.ollama.com/v1
  api_key: ${REVIEWER2_API_KEY}

models:
  fast: kimi-k2.5:cloud       # metadata, compilation, formatting
  strong: kimi-k2.5:cloud     # breaker, reviewer, math audit
  temperature: 0.1
```

Env var overrides: `REVIEWER2_API_KEY`, `REVIEWER2_BASE_URL`,
`REVIEWER2_FAST_MODEL`, `REVIEWER2_STRONG_MODEL`.

Config file search order: `./reviewer2.yaml`,
`~/.config/reviewer2/config.yaml`.

### Two-tier model system

Stages currently request `model_type` like `"flash_lite"` or `"pro_3_1"`.
Map these to two tiers:

- **fast**: all `flash_*` model types (metadata, compilation, formatting)
- **strong**: all `pro_*` model types (breaker, reviewer, math audit)

Users can set one model for both or split them. Default: same model for both.

### Implementation steps

**Step 1: Add `config.py` (new file)**
- Pydantic models for provider config (modeled on `RAiner/rainer/config.py`)
- `ProviderConfig` with `base_url`, `api_key`, `fast_model`, `strong_model`,
  `temperature`
- `load_config()`: YAML file with env var overrides
- Config search: `./reviewer2.yaml`, `~/.config/reviewer2/config.yaml`
- Verify: unit test that loads a sample YAML and env var override works

**Step 2: Rewrite `core.py`**
- Replace `call_gemini()` with `call_llm()` using
  `openai.OpenAI.chat.completions.create()`
- Map `model_type` to tier: `flash_*` -> `config.fast_model`,
  `pro_*` -> `config.strong_model`
- Drop: file upload/caching, thinking config, safety settings,
  `media_resolution`, `google_search` tool
- Keep: retry logic (simplified), usage logging (optional)
- Add: `_PDF_TEXT_CACHE: dict[str, str]` for docling markdown
- When `pdf_file_path` is provided: look up cached markdown, inject into
  prompt
- Verify: `call_llm()` works with Ollama Cloud endpoint

**Step 3: Add docling PDF processing in `pipeline.py`**
- At pipeline start: run docling on the PDF (and any supplements), cache
  the markdown
- Pass markdown string to stages instead of `pdf_file_path`
- Merged-PDF logic stays (pypdf for supplement merging), but the merged
  PDF also gets docling'd
- Remove `cleanup_resources()` call (no remote files to delete)
- Verify: docling converts a sample PDF; pipeline passes markdown through

**Step 4: Update `stages.py`**
- Change import: `call_gemini` -> `call_llm`
- Replace `pdf_path` parameter with `pdf_text` in all stage signatures
- In `stage_00a_metadata` and `stage_03b_external`: replace
  `use_search=True` with rainer search call
- Verify: stages compile; a dry run with one stage produces output

**Step 5: Rainer search integration**
- Optional dependency via `pip install -e /path/to/RAiner` (local editable
  install, not listed in pyproject.toml)
- Guarded import:
  ```python
  try:
      from rainer.search import PaperSearch
      HAS_RAINER = True
  except ImportError:
      HAS_RAINER = False
  ```
- In the two search stages: if `HAS_RAINER`, instantiate `PaperSearch`,
  call `.search(query, top_k=10)`, format results as markdown, inject into
  prompt. If not available, skip silently.
- Verify: with rainer installed, search results appear in stage output;
  without rainer, stages complete normally

**Step 6: Update `helpers.py`**
- Swap `call_gemini` import to `call_llm`
- Simplify `calculate_cost()`: make it a no-op or optional
- `validate_pdf_structure()` and `is_output_truncated()` go through
  `call_llm()` as "fast" tier
- Verify: helper functions work with new `call_llm`

**Step 7: Update `cli.py`**
- Add flags: `--model` (overrides both tiers), `--base-url`,
  `--fast-model`, `--strong-model`, `--config`
- Remove hard `GEMINI_API_KEY` requirement
- Keep all existing flags (`--math`, `--code-dir`, `--base`, `--supp`, etc.)
- Verify: `reviewer2 --help` shows new flags; old flags still work

**Step 8: Update dependencies**
- `pyproject.toml` and `requirements.txt`:
  - Add: `openai`, `docling`
  - Keep: `pypdf` (supplement merging), mathpix deps
  - Move `google-genai` to optional extras `[gemini]`
- Verify: `pip install -e .` works

### Files changed

| File | Change |
|------|--------|
| `src/reviewer2/config.py` | **New**: pydantic config, `load_config()` |
| `src/reviewer2/core.py` | Rewrite: `call_llm()` via OpenAI SDK, docling text cache, tier mapping |
| `src/reviewer2/pipeline.py` | Add docling at start; pass markdown; wire config |
| `src/reviewer2/stages.py` | Swap import; `pdf_path` -> `pdf_text`; rainer in 2 stages |
| `src/reviewer2/helpers.py` | Swap import; simplify cost tracking |
| `src/reviewer2/cli.py` | Add `--model`, `--base-url`, `--fast-model`, `--strong-model`, `--config` |
| `pyproject.toml` | Update deps |
| `requirements.txt` | Update deps |

### What stays the same

- All ~50 prompt templates in `src/reviewer2/prompts/`
- Pipeline orchestration (stage ordering, conditional execution, resumability)
- Stage structure (load prompt, substitute context, call LLM, save output)
- PDF merging for supplements (pypdf)
- Mathpix integration
- Report rendering (`render_text.py`)

### Risks

- **Quality regression**: frontier Ollama models may reason differently than
  Gemini Pro. Mitigation: test with a known paper, compare output quality.
- **docling accuracy**: lossy on figures/tables vs native PDF upload.
  Mitigation: docling handles academic PDFs well; math extraction still
  uses Mathpix separately.
- **Context window**: full PDF markdown may exceed context limits for long
  papers. Mitigation: most stages already receive only relevant excerpts
  via pipeline orchestration; chunk or summarize where needed.

### Blueprint reference

RAiner (`/Users/casparm4/Github/RAiner`) is the blueprint for provider
config, OpenAI SDK usage, and model selection. Key files:

- `rainer/config.py` (lines 15-68): provider config pydantic models
- `rainer/agent.py` (lines 279-324): client init per provider
- `rainer/agent.py` (lines 302-309): OpenAI SDK with base_url for OpenRouter
- `rainer/providers.py` (lines 314-340): adapter factory pattern
- `rainer/search.py`: `PaperSearch` class for literature search
- `rainer/papers.py`: `PaperDB` class for paper database
- `config.yaml`: default config (ollama, kimi-k2.5:cloud, temp 0.1)
