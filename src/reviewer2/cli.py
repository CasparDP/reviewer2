"""Command-line interface for reviewer2."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewer2",
        description="Adversarial peer review for academic PDFs.",
    )
    parser.add_argument("pdf", help="Path to the PDF to review.")
    parser.add_argument(
        "-o", "--output", default="report.txt",
        help="Output text file path. Default: report.txt",
    )

    # ---- review add-ons ----
    parser.add_argument(
        "--math", action="store_true",
        help="Enable the math-audit stages. Requires MATHPIX_APP_ID and MATHPIX_APP_KEY.",
    )
    parser.add_argument(
        "--code-dir", default=None, metavar="PATH",
        help="Path to a directory of replication source code. Enables the code-audit add-on.",
    )
    parser.add_argument(
        "--no-copyedit", action="store_true",
        help="Skip the copyedit stages (proofreading and revision suggestions).",
    )
    parser.add_argument(
        "--no-editor-note", action="store_true",
        help="Skip the editor's-note stage. Disabling either copyedit or editor's note "
             "skips all Writer-Mode stages.",
    )
    parser.add_argument(
        "--base", action="store_true",
        help="Base review only. Disables every add-on: math, code, copyedit, editor's note.",
    )
    parser.add_argument(
        "--supp", action="append", default=[], metavar="PDF",
        help="Path to a supplementary PDF to merge after the main paper. Repeatable.",
    )
    parser.add_argument(
        "--citation", default="",
        help="Manual citation string, used only if metadata extraction fails.",
    )

    # ---- run control ----
    parser.add_argument(
        "--work-dir", default=None,
        help="Directory for intermediate stage outputs. Default: a temp dir cleaned up on "
             "success. Pass an explicit path to keep outputs or resume a previous run.",
    )
    parser.add_argument(
        "--keep-work-dir", action="store_true",
        help="Keep intermediate stage outputs after the run completes.",
    )
    parser.add_argument(
        "--skip-size-check", action="store_true",
        help="Bypass the 500-page combined-volume circuit breaker.",
    )

    # ---- LLM provider ----
    parser.add_argument(
        "--config", default=None, metavar="PATH",
        help="Path to a reviewer2.yaml config file. Defaults to ./reviewer2.yaml or "
             "~/.config/reviewer2/config.yaml.",
    )
    parser.add_argument(
        "--base-url", default=None, metavar="URL",
        help="Override the LLM provider base URL (e.g. https://api.openai.com/v1).",
    )
    parser.add_argument(
        "--model", default=None, metavar="MODEL",
        help="Set both fast and strong model tiers to MODEL.",
    )
    parser.add_argument(
        "--fast-model", default=None, metavar="MODEL",
        help="Override the fast-tier model (used for metadata, formatting stages).",
    )
    parser.add_argument(
        "--strong-model", default=None, metavar="MODEL",
        help="Override the strong-tier model (used for breaker, reviewer, math stages).",
    )

    return parser


def resolve_addons(args: argparse.Namespace) -> dict[str, bool]:
    """Collapse CLI flags into a stage-enable map matching pipeline.run kwargs."""
    if args.base:
        return {"math": False, "code": False, "copyedit": False, "editor_note": False}
    return {
        "math": args.math,
        "code": bool(args.code_dir),
        "copyedit": not args.no_copyedit,
        "editor_note": not args.no_editor_note,
    }


def _require_env(var: str, because: str) -> None:
    if not os.environ.get(var):
        print(f"error: {var} not set. Required {because}.", file=sys.stderr)
        sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.exists():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    addons = resolve_addons(args)
    if addons["math"]:
        _require_env("MATHPIX_APP_ID", "for the --math add-on")
        _require_env("MATHPIX_APP_KEY", "for the --math add-on")

    # Apply CLI provider overrides as env vars so load_config() picks them up.
    if args.base_url:
        os.environ["REVIEWER2_BASE_URL"] = args.base_url
    if args.model:
        os.environ["REVIEWER2_FAST_MODEL"] = args.model
        os.environ["REVIEWER2_STRONG_MODEL"] = args.model
    if args.fast_model:
        os.environ["REVIEWER2_FAST_MODEL"] = args.fast_model
    if args.strong_model:
        os.environ["REVIEWER2_STRONG_MODEL"] = args.strong_model

    # Load config now and inject into core so all stages share the same instance.
    from reviewer2.config import load_config
    import reviewer2.core as _core
    _core._config = load_config(args.config)

    if not _core._config.provider.api_key:
        print(
            "warning: REVIEWER2_API_KEY not set. Requests will likely fail unless "
            "the provider does not require authentication.",
            file=sys.stderr,
        )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.work_dir:
        work_dir = Path(args.work_dir).expanduser().resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        cleanup_work_dir = False
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="reviewer2_"))
        cleanup_work_dir = not args.keep_work_dir

    # Defer pipeline import to keep --help fast.
    from reviewer2.pipeline import PipelineError, run

    try:
        final_txt = run(
            pdf_path=pdf_path,
            work_dir=work_dir,
            math=addons["math"],
            code=addons["code"],
            copyedit=addons["copyedit"],
            editor_note=addons["editor_note"],
            supp_pdfs=args.supp or None,
            code_dir=args.code_dir,
            citation=args.citation,
            skip_size_check=args.skip_size_check,
        )
    except PipelineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\naborted by user", file=sys.stderr)
        return 130

    if final_txt and Path(final_txt).is_file():
        shutil.copy2(final_txt, output_path)
        print(f"\n✓ Report written to {output_path}")
    else:
        print(f"\nerror: pipeline did not produce a final report (stopped at {final_txt})", file=sys.stderr)
        return 1

    if cleanup_work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)
    elif not args.work_dir:
        print(f"  (intermediate outputs kept at {work_dir})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
