"""LLM client (OpenAI-compatible) with retry logic and PDF text cache."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader, PdfWriter

from reviewer2.config import Config, load_config
from reviewer2.paths import prompts_dir

# Per-call usage records.
USAGE_LOG: list[dict] = []

# { local_file_path: markdown_text } — populated by pipeline before stages run.
_PDF_TEXT_CACHE: dict[str, str] = {}

# Lazy-loaded config singleton (overridable by passing config= to call_llm).
_config: Config | None = None


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _resolve_model(model_type: str, config: Config) -> str:
    """Map model_type tier to the configured model name."""
    if model_type.startswith("flash"):
        return config.provider.fast_model
    if model_type.startswith("pro"):
        return config.provider.strong_model
    # Unknown type: treat as a literal model name.
    return model_type


def _make_client(config: Config) -> OpenAI:
    return OpenAI(
        api_key=config.provider.api_key or "no-key",
        base_url=config.provider.base_url,
    )


def call_llm(
    prompt: str | None = None,
    pdf_file_path: str | None = None,
    model_type: str = "flash_lite",
    temperature: float | None = None,
    system_instruction: str | None = None,
    max_retries: int = 10,
    retry_forever_on_rate_limit: bool = True,
    step: str | None = None,
    max_output_tokens: int | None = None,
    config: Config | None = None,
) -> str:
    """Call an OpenAI-compatible LLM with retries.

    If pdf_file_path is given, the cached markdown for that path is injected
    at the top of the prompt (populated by pipeline via _PDF_TEXT_CACHE).
    """
    cfg = config or _get_config()
    model_name = _resolve_model(model_type, cfg)

    # Build the user message content.
    content_parts: list[str] = []
    if pdf_file_path:
        cached_text = _PDF_TEXT_CACHE.get(pdf_file_path)
        if cached_text:
            content_parts.append(f"<paper>\n{cached_text}\n</paper>")
        else:
            print(f"  ⚠  No cached text for {pdf_file_path}; PDF content will be missing.")
    if prompt:
        content_parts.append(prompt)

    user_content = "\n\n".join(content_parts)

    messages: list[dict] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": user_content})

    client = _make_client(cfg)

    attempt = 0
    base_delay = 5
    max_delay = 300

    while True:
        attempt += 1
        try:
            kwargs: dict = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature if temperature is not None else cfg.provider.temperature,
            }
            if max_output_tokens:
                kwargs["max_tokens"] = max_output_tokens

            response = client.chat.completions.create(**kwargs)

            usage = getattr(response, "usage", None)
            if usage:
                USAGE_LOG.append({
                    "model_name": model_name,
                    "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "timestamp": datetime.now().isoformat(),
                    "step": step or "unknown",
                })

            result = response.choices[0].message.content
            if not result or not result.strip():
                raise ValueError("API returned empty string")
            return result

        except Exception as e:
            err_str = str(e)

            if "FATAL" in err_str:
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)

            if "429" in err_str:
                print(f"    ↳ Rate limited (429) on attempt {attempt}. Waiting {delay}s...")
                time.sleep(delay)
                if not retry_forever_on_rate_limit and attempt >= max_retries:
                    raise RuntimeError(f"Rate limit exceeded after {attempt} attempts: {err_str}")
                continue
            elif "500" in err_str or "502" in err_str or "503" in err_str:
                print(f"    ⚠  Server error on attempt {attempt}. Waiting {delay}s...")
                time.sleep(delay)
                if attempt >= max_retries:
                    raise RuntimeError(f"Server error after {attempt} attempts: {err_str}")
                continue
            elif "Server disconnected" in err_str or "RemoteProtocolError" in err_str:
                print(f"    ⚠  Network timeout (attempt {attempt}/{max_retries}). Retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"    ⚠  API error (attempt {attempt}/{max_retries}): {err_str[:200]}")
                time.sleep(min(delay, 30))

            if attempt >= max_retries:
                raise RuntimeError(f"LLM call failed after {attempt} attempts. Last error: {err_str}")


def save_output(content, filename, output_dir):
    if content is None:
        print(f"  ⚠  WARNING: content is None for {filename}. Creating empty file.")
        content = ""
    with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✓ Saved: {filename}")


def load_prompt(prompt_path):
    """Load a prompt file and inline the ``{{OUTPUT_FORMAT}}`` resource if referenced.

    A relative path of the form ``prompts/<name>`` resolves against the packaged
    prompts directory (overridable via ``REVIEWER2_PROMPTS_DIR``), so pipeline
    callers can keep using short literals regardless of cwd.
    """
    path = Path(prompt_path)
    if not path.is_absolute() and path.parts and path.parts[0] == "prompts":
        path = prompts_dir().joinpath(*path.parts[1:])

    if not path.exists():
        return f"[Error: Prompt file {path} missing]"

    text = path.read_text(encoding="utf-8")

    if "{{OUTPUT_FORMAT}}" in text:
        output_format_path = prompts_dir() / "resources" / "output_format.txt"
        if output_format_path.exists():
            text = text.replace("{{OUTPUT_FORMAT}}", output_format_path.read_text(encoding="utf-8"))
        else:
            text = text.replace("{{OUTPUT_FORMAT}}", "")
    return text


def sanitize_pdf_ghostscript(input_path):
    if os.path.getsize(input_path) == 0:
        return input_path

    fd, fixed_path = tempfile.mkstemp(suffix=".pdf", prefix="sanitized_")
    os.close(fd)

    gs_cmd = shutil.which("gs")
    if gs_cmd:
        cmd = [gs_cmd, "-o", fixed_path, "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/prepress", "-dQUIET", input_path]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(fixed_path) and os.path.getsize(fixed_path) > 0:
                return fixed_path
        except subprocess.CalledProcessError:
            pass

    try:
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.write(fixed_path)
        return fixed_path
    except Exception:
        pass

    return input_path


def merge_pdfs_python(main_pdf, supplement_source, output_dir=None):
    if output_dir:
        output_path = os.path.join(output_dir, os.path.basename(main_pdf))
    else:
        output_path = main_pdf

    temp_path = output_path + ".tmp_merging"

    writer = PdfWriter()
    page_info = {"pages": []}

    supplement_pdfs = []
    if isinstance(supplement_source, list):
        supplement_pdfs = supplement_source
    elif isinstance(supplement_source, str) and os.path.isdir(supplement_source):
        files = sorted(os.listdir(supplement_source))
        supplement_pdfs = [os.path.join(supplement_source, f) for f in files if f.lower().endswith(".pdf")]

    try:
        reader = PdfReader(main_pdf)
        main_page_count = len(reader.pages)
        for page in reader.pages:
            writer.add_page(page)
        page_info["pages"].append({
            "name": "Main document",
            "pages": main_page_count,
            "numbering": "See main text page numbers",
            "pdf_start": 1,
            "pdf_end": main_page_count,
        })
    except Exception as e:
        print(f"  ✗ Error merging main PDF: {e}")
        return main_pdf, page_info

    current_pdf_page = main_page_count + 1

    if supplement_pdfs:
        sep_path = prompts_dir() / "resources" / "separator_supp.pdf"
        if sep_path.exists():
            try:
                sep_reader = PdfReader(str(sep_path))
                sep_count = len(sep_reader.pages)
                for page in sep_reader.pages:
                    writer.add_page(page)
                current_pdf_page += sep_count
            except Exception as e:
                print(f"  ⚠ Warning: Could not merge separator: {e}")
        else:
            print(f"  ⚠ Warning: Separator file not found at {sep_path}")

    for _i, supp_pdf in enumerate(supplement_pdfs, 1):
        try:
            reader = PdfReader(supp_pdf)
            supp_page_count = len(reader.pages)
            for page in reader.pages:
                writer.add_page(page)

            first_page_text = ""
            try:
                first_page_text = reader.pages[0].extract_text()
            except Exception:
                pass

            numbering = "Unknown"
            if re.search(r"\bS\d+\b", first_page_text):
                numbering = "S-numbered"
            elif re.search(r"\bAppendix\s+[A-Z]\b", first_page_text, re.IGNORECASE):
                numbering = "Appendix-lettered"

            filename = os.path.basename(supp_pdf)
            display_name = re.sub(r"^\d+_\d+_", "", filename)
            page_info["pages"].append({
                "name": display_name,
                "pages": supp_page_count,
                "numbering": numbering,
                "pdf_start": current_pdf_page,
                "pdf_end": current_pdf_page + supp_page_count - 1,
            })
            current_pdf_page += supp_page_count
        except Exception as e:
            print(f"  ⚠  Skipped corrupt supplement {supp_pdf}: {e}")

    with open(temp_path, "wb") as f:
        writer.write(f)
    if os.path.exists(output_path):
        os.remove(output_path)
    shutil.move(temp_path, output_path)
    return output_path, page_info
