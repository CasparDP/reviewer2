---
project:
  name: "reviewer2"
  description: >
    reviewer2
  added_at: 2026-05-21
  github_url: "https://github.com/CasparDP/reviewer2"

current_focus: 1

milestones:
  - id: 1
    title: "Fork Identity & Community-Ready Public Repo"
    description: >
      The repo clearly signals it is a fork, explains what changed and why,
      and has enough documentation that an outside researcher can install and
      run it without asking you. Done when: README prominently credits the
      upstream, lists all fork-specific changes, and includes a short 'Why
      this fork?' section; a CONTRIBUTING or Usage note covers the community
      use-case.
    status: pending
    created_at: 2026-05-21
    next_task: |
      Add a 'This is a fork of…' callout block at the top of README.md (above the feature table) and write a 2–3 sentence 'Why this fork?' paragraph explaining the provider-agnostic motivation.

  - id: 2
    title: "Stable v1.x Release with Passing Smoke Test"
    description: >
      A tagged release (v1.x) exists whose `--base` smoke test completes
      end-to-end on a short PDF without manual intervention. Done when:
      version strings are in sync across pyproject.toml / __init__.py /
      README, a GitHub Release is published, and the smoke-test command is
      documented in the README.
    status: pending
    created_at: 2026-05-21
    next_task: |
      Run `grep -r 'version' pyproject.toml src/reviewer2/__init__.py README.md` to confirm all three are in sync, then cut the v1.0.1 (or v1.1.0) tag and push it with a GitHub Release entry.

  - id: 3
    title: "SSRN Keyword Search Tool (Standalone)"
    description: >
      A minimal CLI tool (or importable module) that accepts a keyword query
      and returns a ranked list of SSRN paper titles, authors, abstracts, and
      URLs — callable independently of the review pipeline. Done when:
      `reviewer2-search 'keyword query' --source ssrn` returns ≥5 results as
      structured JSON/text and is documented in the README.
    status: pending
    created_at: 2026-05-21
    next_task: |
      Prototype a Python script that fetches the SSRN search endpoint (https://api.ssrn.com/content/v1/bindings?query=…) or scrapes the search results page for a hardcoded test query and prints titles + URLs.

  - id: 4
    title: "Integrate Working Paper Search into Review Workflow"
    description: >
      The standalone search tool is wired into the pipeline as an optional
      enrichment step (alongside RAiner), so stage 03b can cite recent SSRN
      working papers. Done when: passing `--ssrn-search` to the CLI triggers a
      keyword search derived from the paper's title/abstract and injects
      results into the literature context the same way RAiner does.
    status: pending
    created_at: 2026-05-21
    next_task: |
      Read stages.py to find exactly where RAiner results are injected (stages 00a and 03b per CLAUDE.md), then sketch the interface a new `ssrn_search(query) -> list[dict]` function needs to match.

  - id: 5
    title: "Personal Website Integration & Reproducible Example"
    description: >
      The public-facing website reference is backed by a worked example: a
      sample output report (anonymised or synthetic) plus a one-command
      reproduction script, so visitors can see what the tool produces. Done
      when: a `examples/` folder contains one sample PDF, its generated
      report, and a shell script that reproduces the run with `--base`.
    status: pending
    created_at: 2026-05-21
    next_task: |
      Pick a short open-access paper you've already reviewed, sanitise the output, and commit it to `examples/sample_report.txt` alongside the source PDF (or a DOI pointer if the PDF is too large).

checkin:
  last_at: null
  last_commit_seen: null
  last_summary: null

integrations:
  github: "https://github.com/CasparDP/reviewer2"
---
