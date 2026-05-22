from __future__ import annotations

import asyncio
import html
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path

from quart import Quart, Response, abort, jsonify, request, send_file, websocket

ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "outputs"
PROMPT_HISTORY_PATH = ROOT / "prompt_history.json"
MAX_PROMPT_HISTORY = 100
HOST = "127.0.0.1"
PORT = 5002
app = Quart(__name__)
JOBS: dict[str, dict[str, object]] = {}
MAX_COMPLETED_JOBS = 20

MODELS = {
    "zimage": {
        "label": "Z-Image Turbo",
        "command": ROOT / ".venv/bin/mflux-generate-z-image-turbo",
        "extra_args": [],
        "default_steps": 9,
        "filename_prefix": "zimage",
    },
    "flux2": {
        "label": "Flux 2 Klein 4B",
        "command": ROOT / ".venv/bin/mflux-generate-flux2",
        "extra_args": ["--model", "flux2-klein-4b"],
        "default_steps": 4,
        "filename_prefix": "flux",
    },
    "qwen": {
        "label": "Qwen Image",
        "command": ROOT / ".venv/bin/mflux-generate-qwen",
        "extra_args": [
            "--negative-prompt", "blurry, low quality, distorted, deformed, ugly, bad anatomy, bad proportions, extra limbs, duplicate, watermark, signature, text, letters, cartoon, anime, painting, drawing, illustration, 3d render, cgi, zoo, cage, artificial",
            "--lora-paths", "/Users/ericchan/Project/image/lora/Qwen-Image-Lightning-8steps-V2.0.safetensors",
            "--lora-scales", "0.5",
        ],
        "default_steps": 8,
        "filename_prefix": "qwen",
    },
}

SAFE_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def field(form: dict[str, str], name: str, default: str = "") -> str:
    return form.get(name, default).strip()


def load_prompt_history() -> list[str]:
    try:
        data = json.loads(PROMPT_HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    prompts: list[str] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, str):
            continue
        prompt = item.strip()
        if not prompt or prompt in seen:
            continue
        prompts.append(prompt)
        seen.add(prompt)
        if len(prompts) >= MAX_PROMPT_HISTORY:
            break
    return prompts


def save_prompt_history(prompts: list[str]) -> None:
    normalized: list[str] = []
    seen: set[str] = set()
    for prompt in prompts:
        cleaned = prompt.strip()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
        if len(normalized) >= MAX_PROMPT_HISTORY:
            break

    PROMPT_HISTORY_PATH.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")


def add_prompt_history(prompt: str) -> list[str]:
    cleaned = prompt.strip()
    if not cleaned:
        return load_prompt_history()

    prompts = [item for item in load_prompt_history() if item != cleaned]
    prompts.insert(0, cleaned)
    save_prompt_history(prompts)
    return load_prompt_history()


def delete_prompt_history(prompt: str) -> list[str]:
    cleaned = prompt.strip()
    prompts = [item for item in load_prompt_history() if item != cleaned]
    save_prompt_history(prompts)
    return load_prompt_history()


def parse_int(value: str, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc

    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def default_filename_prefix(model: str) -> str:
    model_config = MODELS.get(model, MODELS["zimage"])
    return str(model_config["filename_prefix"])


def timestamped_filename(prefix: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{timestamp}.png"


def sanitize_filename_prefix(raw_prefix: str, model: str) -> str:
    prefix = raw_prefix.strip() or default_filename_prefix(model)

    if "/" in prefix or "\\" in prefix or prefix != Path(prefix).name:
        raise ValueError("Output filename prefix must be a simple name, not a path.")

    if not SAFE_PREFIX_RE.fullmatch(prefix):
        raise ValueError("Output filename prefix can only contain letters, numbers, underscores, and hyphens.")

    return prefix


def output_filename(prefix: str, now: datetime | None = None) -> str:
    return timestamped_filename(prefix, now)


def default_upscale_resolution(width: int, height: int) -> int:
    return min(width, height) * 2


def validate_form(form: dict[str, str]) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    model = field(form, "model", "zimage")
    prompt = field(form, "prompt")
    random_seed = "random_seed" in form
    upscale_enabled = "upscale_enabled" in form

    if model not in MODELS:
        errors.append("Choose either zimage or flux2.")

    if not prompt:
        errors.append("Prompt is required.")

    try:
        width = parse_int(field(form, "width", "512"), "Width", 64, 2048)
    except ValueError as exc:
        errors.append(str(exc))
        width = 512

    try:
        height = parse_int(field(form, "height", "512"), "Height", 64, 2048)
    except ValueError as exc:
        errors.append(str(exc))
        height = 512

    try:
        steps_default = str(MODELS.get(model, MODELS["zimage"])["default_steps"])
        steps = parse_int(field(form, "steps", steps_default), "Steps", 1, 100)
    except ValueError as exc:
        errors.append(str(exc))
        steps = int(MODELS["zimage"]["default_steps"])

    if random_seed:
        seed = random.randint(0, 2**32 - 1)
    else:
        try:
            seed = parse_int(field(form, "seed", "42"), "Seed", 0, 2**32 - 1)
        except ValueError as exc:
            errors.append(str(exc))
            seed = 42

    valid_model = model if model in MODELS else "zimage"
    try:
        filename_prefix = sanitize_filename_prefix(field(form, "filename_prefix"), valid_model)
    except ValueError as exc:
        errors.append(str(exc))
        filename_prefix = default_filename_prefix(valid_model)

    default_resolution = default_upscale_resolution(width, height)
    upscale_resolution_raw = field(form, "upscale_resolution")
    if upscale_enabled and upscale_resolution_raw:
        try:
            upscale_resolution = parse_int(upscale_resolution_raw, "Upscale resolution", 64, 8192)
        except ValueError as exc:
            errors.append(str(exc))
            upscale_resolution = default_resolution
    else:
        upscale_resolution = default_resolution

    values: dict[str, object] = {
        "model": valid_model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "random_seed": random_seed,
        "filename_prefix": filename_prefix,
        "filename": output_filename(filename_prefix),
        "upscale_enabled": upscale_enabled,
        "upscale_resolution": upscale_resolution,
        "upscale_resolution_raw": upscale_resolution_raw,
    }
    return values, errors


async def emit_job_message(job: dict[str, object], message: dict[str, object]) -> None:
    messages = job.setdefault("messages", [])
    if isinstance(messages, list):
        messages.append(message)

    queue = job.get("queue")
    if isinstance(queue, asyncio.Queue):
        await queue.put(message)


async def set_job_status(job: dict[str, object], status: str, phase: str, message: str) -> None:
    job["status"] = status
    await emit_job_message(job, {"type": "status", "status": status, "phase": phase, "message": message})


def prune_completed_jobs() -> None:
    completed = [
        job_id
        for job_id, job in JOBS.items()
        if job.get("status") in {"done", "error"}
    ]
    for job_id in completed[:-MAX_COMPLETED_JOBS]:
        JOBS.pop(job_id, None)


def normalize_progress_message(message: str) -> str:
    return ANSI_ESCAPE_RE.sub("", message).strip()


def split_progress_buffer(buffer: str) -> tuple[list[str], str]:
    parts: list[str] = []
    start = 0
    for index, character in enumerate(buffer):
        if character in {"\r", "\n"}:
            parts.append(buffer[start:index])
            start = index + 1
    return parts, buffer[start:]


async def collect_process_stream(
    stream: asyncio.StreamReader | None,
    stream_name: str,
    phase: str,
    job: dict[str, object],
    lines: list[str],
) -> None:
    if stream is None:
        return

    buffer = ""
    while True:
        raw_chunk = await stream.read(128)
        if not raw_chunk:
            break
        buffer += raw_chunk.decode("utf-8", errors="replace")
        parts, buffer = split_progress_buffer(buffer)
        for part in parts:
            line = normalize_progress_message(part)
            if not line:
                continue
            lines.append(line)
            await emit_job_message(
                job,
                {
                    "type": "log",
                    "phase": phase,
                    "stream": stream_name,
                    "message": line,
                },
            )

    final_line = normalize_progress_message(buffer)
    if final_line:
        lines.append(final_line)
        await emit_job_message(
            job,
            {
                "type": "log",
                "phase": phase,
                "stream": stream_name,
                "message": final_line,
            },
        )


async def run_command(command: list[str], phase: str, job: dict[str, object]) -> tuple[int, list[str], list[str]]:
    await emit_job_message(
        job,
        {
            "type": "log",
            "phase": phase,
            "stream": "command",
            "message": " ".join(command),
        },
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout: list[str] = []
    stderr: list[str] = []
    await asyncio.gather(
        collect_process_stream(process.stdout, "stdout", phase, job, stdout),
        collect_process_stream(process.stderr, "stderr", phase, job, stderr),
    )
    return_code = await process.wait()
    return return_code, stdout, stderr


async def run_upscale(image_path: Path, resolution: int, job: dict[str, object]) -> dict[str, object]:
    command_path = ROOT / ".venv/bin/mflux-upscale-seedvr2"
    output_path = image_path.with_name(f"upscaled-{image_path.name}")

    if not command_path.exists():
        await emit_job_message(
            job,
            {
                "type": "log",
                "phase": "upscaling",
                "stream": "stderr",
                "message": f"Upscale command not found: {command_path}",
            },
        )
        return {
            "success": False,
            "error": f"Upscale command not found: {command_path}",
            "stdout": "",
            "stderr": "",
            "command": [],
            "output_path": output_path,
        }

    command = [
        str(command_path),
        "--image-path",
        str(image_path),
        "--resolution",
        str(resolution),
        "--softness",
        "0.5",
        "--output",
        str(output_path),
    ]

    try:
        return_code, stdout, stderr = await run_command(command, "upscaling", job)
    except OSError as exc:
        await emit_job_message(
            job,
            {
                "type": "log",
                "phase": "upscaling",
                "stream": "stderr",
                "message": str(exc),
            },
        )
        return {
            "success": False,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
            "command": command,
            "output_path": output_path,
        }

    success = return_code == 0 and output_path.exists()
    return {
        "success": success,
        "error": "" if success else f"Upscale failed with exit code {return_code}.",
        "stdout": "\n".join(stdout),
        "stderr": "\n".join(stderr),
        "command": command,
        "output_path": output_path,
        "image_url": f"/outputs/{output_path.name}" if success else "",
        "resolution": resolution,
    }


async def run_generation(values: dict[str, object], job: dict[str, object]) -> dict[str, object]:
    model_name = str(values["model"])
    model = MODELS[model_name]
    command_path = Path(model["command"])

    if not command_path.exists():
        await emit_job_message(
            job,
            {
                "type": "log",
                "phase": "generating",
                "stream": "stderr",
                "message": f"Generator command not found: {command_path}",
            },
        )
        return {
            "success": False,
            "error": f"Generator command not found: {command_path}",
            "stdout": "",
            "stderr": "",
        }

    OUTPUTS_DIR.mkdir(exist_ok=True)
    output_path = OUTPUTS_DIR / str(values["filename"])
    command = [
        str(command_path),
        *model["extra_args"],
        "--prompt",
        str(values["prompt"]),
        "--width",
        str(values["width"]),
        "--height",
        str(values["height"]),
        "--seed",
        str(values["seed"]),
        "--steps",
        str(values["steps"]),
        "-q",
        "8",
        "--output",
        str(output_path),
    ]

    try:
        return_code, stdout, stderr = await run_command(command, "generating", job)
    except OSError as exc:
        await emit_job_message(
            job,
            {
                "type": "log",
                "phase": "generating",
                "stream": "stderr",
                "message": str(exc),
            },
        )
        return {
            "success": False,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
            "command": command,
        }

    success = return_code == 0 and output_path.exists()
    return {
        "success": success,
        "error": "" if success else f"Generation failed with exit code {return_code}.",
        "stdout": "\n".join(stdout),
        "stderr": "\n".join(stderr),
        "command": command,
        "output_path": output_path,
        "image_url": f"/outputs/{output_path.name}" if success else "",
    }


async def run_generation_with_optional_upscale(values: dict[str, object], job: dict[str, object]) -> dict[str, object]:
    await set_job_status(job, "generating", "generating", "Generating image...")
    result = await run_generation(values, job)
    if not result.get("success") or not values.get("upscale_enabled"):
        return result

    await set_job_status(job, "upscaling", "upscaling", "Upscaling image...")
    result["upscale"] = await run_upscale(Path(result["output_path"]), int(values["upscale_resolution"]), job)
    return result


async def run_job(job_id: str) -> None:
    job = JOBS[job_id]
    values = job["values"]
    try:
        if isinstance(values, dict):
            await asyncio.to_thread(add_prompt_history, str(values["prompt"]))
            result = await run_generation_with_optional_upscale(values, job)
            job["result"] = result
            status = "done" if result.get("success") else "error"
            final_html = render_result(result, values)
            await emit_job_message(
                job,
                {
                    "type": "done" if status == "done" else "error",
                    "status": status,
                    "phase": "done" if status == "done" else "error",
                    "result_html": final_html,
                },
            )
            job["status"] = status
    except Exception as exc:
        job["status"] = "error"
        result = {
            "success": False,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
            "command": [],
        }
        job["result"] = result
        await emit_job_message(
            job,
            {
                "type": "error",
                "status": "error",
                "phase": "error",
                "message": str(exc),
                "result_html": render_result(result, values if isinstance(values, dict) else {}),
            },
        )
    finally:
        prune_completed_jobs()


def page(values: dict[str, object] | None = None, result: dict[str, object] | None = None, errors: list[str] | None = None) -> str:
    values = values or {
        "model": "zimage",
        "prompt": "A puffin standing on a cliff",
        "width": 512,
        "height": 512,
        "steps": MODELS["zimage"]["default_steps"],
        "seed": 42,
        "random_seed": False,
        "filename_prefix": default_filename_prefix("zimage"),
        "filename": "",
        "upscale_enabled": False,
        "upscale_resolution": 1024,
        "upscale_resolution_raw": "",
    }
    errors = errors or []
    client_defaults = {
        name: {
            "steps": config["default_steps"],
            "filenamePrefix": config["filename_prefix"],
        }
        for name, config in MODELS.items()
    }
    client_defaults_json = json.dumps(client_defaults)

    model_options = "\n".join(
        f'<option value="{html.escape(name)}" {"selected" if values["model"] == name else ""}>{html.escape(config["label"])}</option>'
        for name, config in MODELS.items()
    )
    checked = "checked" if values.get("random_seed") else ""
    upscale_checked = "checked" if values.get("upscale_enabled") else ""
    error_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        error_html = f'<div class="alert error"><strong>Fix these fields:</strong><ul>{items}</ul></div>'

    result_html = render_result(result, values)

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Image Generator</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #1e2428;
      --muted: #626b73;
      --line: #d9dedb;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --error-bg: #fff1f0;
      --error-text: #9f1d1d;
      --ok-bg: #eefbf4;
      --ok-text: #17633a;
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #111514;
        --panel: #1a201f;
        --text: #edf3f1;
        --muted: #a7b1ad;
        --line: #33413d;
        --accent: #2dd4bf;
        --accent-dark: #5eead4;
        --error-bg: #36191a;
        --error-text: #ffc7c2;
        --ok-bg: #123225;
        --ok-text: #a8f0c9;
      }}
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}

    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 32px auto;
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 24px;
      align-items: start;
    }}

    h1 {{
      margin: 0 0 16px;
      font-size: 28px;
      line-height: 1.15;
    }}

    form, .result {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }}

    label {{
      display: block;
      margin: 14px 0 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }}

    input, select, textarea, button {{
      width: 100%;
      font: inherit;
    }}

    input, select, textarea {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      background: color-mix(in srgb, var(--panel) 94%, var(--bg));
      color: var(--text);
    }}

    textarea {{
      min-height: 110px;
      resize: vertical;
    }}

    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}

    .prompt-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin: 14px 0 6px;
    }}

    .prompt-header label {{
      margin: 0;
    }}

    .checkbox {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 14px;
      color: var(--text);
      font-size: 14px;
      font-weight: 500;
    }}

    .checkbox input {{
      width: auto;
      min-width: 18px;
      height: 18px;
    }}

    button {{
      margin-top: 18px;
      border: 0;
      border-radius: 6px;
      padding: 12px 14px;
      background: var(--accent);
      color: #06201d;
      font-weight: 750;
      cursor: pointer;
    }}

    button:hover {{
      background: var(--accent-dark);
    }}

    button.secondary, .history-actions button {{
      width: auto;
      margin-top: 0;
      padding: 8px 10px;
      background: transparent;
      border: 1px solid var(--line);
      color: var(--text);
      font-size: 13px;
      font-weight: 650;
    }}

    button.secondary:hover, .history-actions button:hover {{
      background: color-mix(in srgb, var(--panel) 78%, var(--accent));
    }}

    button.danger {{
      color: var(--error-text);
    }}

    .alert {{
      border-radius: 8px;
      padding: 12px 14px;
      margin-bottom: 16px;
    }}

    .alert ul {{
      margin: 8px 0 0;
      padding-left: 20px;
    }}

    .error {{
      background: var(--error-bg);
      color: var(--error-text);
    }}

    .ok {{
      background: var(--ok-bg);
      color: var(--ok-text);
    }}

    .result h2 {{
      margin: 0 0 12px;
      font-size: 20px;
    }}

    .meta {{
      color: var(--muted);
      font-size: 14px;
      margin: 8px 0;
      overflow-wrap: anywhere;
    }}

    img {{
      display: block;
      max-width: 100%;
      height: auto;
      margin-top: 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #fff;
    }}

    pre {{
      max-height: 280px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: color-mix(in srgb, var(--panel) 88%, #000);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}

    .progress-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }}

    .progress-status {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 650;
    }}

    .progress-log {{
      height: 320px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: color-mix(in srgb, var(--panel) 88%, #000);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      max-width: 100%;
      white-space: pre-wrap;
      overflow-x: hidden;
      word-break: break-word;
      overflow-wrap: anywhere;
      user-select: text;
    }}

    .progress-result {{
      margin-bottom: 16px;
    }}

    .modal {{
      position: fixed;
      inset: 0;
      display: none;
      place-items: center;
      padding: 20px;
      background: rgb(0 0 0 / 0.45);
      z-index: 10;
    }}

    .modal[aria-hidden="false"] {{
      display: grid;
    }}

    .modal-panel {{
      width: min(760px, 100%);
      max-height: min(680px, calc(100vh - 40px));
      display: flex;
      flex-direction: column;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}

    .modal-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
    }}

    .modal-header h2 {{
      margin: 0;
      font-size: 18px;
    }}

    .history-list {{
      padding: 12px;
      overflow: auto;
    }}

    .history-item {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: start;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }}

    .history-item:last-child {{
      border-bottom: 0;
    }}

    .history-text {{
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }}

    .history-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .empty-history {{
      margin: 0;
      padding: 18px;
      color: var(--muted);
    }}

    @media (max-width: 820px) {{
      main {{
        grid-template-columns: 1fr;
        margin-top: 18px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section>
      <h1>MFLUX Image Generator</h1>
      <div id="form-errors">{error_html}</div>
      <form id="generator-form" method="post" action="/generate">
        <label for="model">Model</label>
        <select id="model" name="model">{model_options}</select>

        <div class="prompt-header">
          <label for="prompt">Prompt</label>
          <button id="history-button" class="secondary" type="button">Prompt History</button>
        </div>
        <textarea id="prompt" name="prompt" required>{html.escape(str(values["prompt"]))}</textarea>

        <div class="grid">
          <div>
            <label for="width">Width</label>
            <input id="width" name="width" type="number" min="64" max="2048" step="1" value="{html.escape(str(values["width"]))}">
          </div>
          <div>
            <label for="height">Height</label>
            <input id="height" name="height" type="number" min="64" max="2048" step="1" value="{html.escape(str(values["height"]))}">
          </div>
        </div>

        <div class="grid">
          <div>
            <label for="seed">Seed</label>
            <input id="seed" name="seed" type="number" min="0" max="{2**32 - 1}" step="1" value="{html.escape(str(values["seed"]))}">
          </div>
          <div>
            <label for="steps">Steps</label>
            <input id="steps" name="steps" type="number" min="1" max="100" step="1" value="{html.escape(str(values["steps"]))}">
          </div>
        </div>

        <label class="checkbox">
          <input type="checkbox" name="random_seed" value="1" {checked}>
          Use random seed
        </label>

        <label class="checkbox">
          <input id="upscale_enabled" type="checkbox" name="upscale_enabled" value="1" {upscale_checked}>
          Upscale result image
        </label>

        <label for="upscale_resolution">Upscale resolution</label>
        <input id="upscale_resolution" name="upscale_resolution" type="number" min="64" max="8192" step="1" value="{html.escape(str(values["upscale_resolution_raw"]))}" placeholder="{html.escape(str(values["upscale_resolution"]))}">

        <label for="filename_prefix">Output filename prefix</label>
        <input id="filename_prefix" name="filename_prefix" value="{html.escape(str(values["filename_prefix"]))}" placeholder="zimage">

        <button id="generate-button" type="submit">Generate Image</button>
      </form>
    </section>
    <div id="result-slot">{result_html}</div>
  </main>
  <div id="history-modal" class="modal" aria-hidden="true">
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <div class="modal-header">
        <h2 id="history-title">Prompt History</h2>
        <button id="history-close" class="secondary" type="button">Close</button>
      </div>
      <div id="history-list" class="history-list">
        <p class="empty-history">No prompts saved yet.</p>
      </div>
    </section>
  </div>
  <script>
    const modelDefaults = {client_defaults_json};
    const modelSelect = document.getElementById("model");
    const promptInput = document.getElementById("prompt");
    const widthInput = document.getElementById("width");
    const heightInput = document.getElementById("height");
    const stepsInput = document.getElementById("steps");
    const filenamePrefixInput = document.getElementById("filename_prefix");
    const upscaleResolutionInput = document.getElementById("upscale_resolution");
    const form = document.getElementById("generator-form");
    const formErrors = document.getElementById("form-errors");
    const resultSlot = document.getElementById("result-slot");
    const button = document.getElementById("generate-button");
    const historyButton = document.getElementById("history-button");
    const historyModal = document.getElementById("history-modal");
    const historyClose = document.getElementById("history-close");
    const historyList = document.getElementById("history-list");

    function openHistoryModal() {{
      historyModal.setAttribute("aria-hidden", "false");
      loadPromptHistory();
    }}

    function closeHistoryModal() {{
      historyModal.setAttribute("aria-hidden", "true");
    }}

    function renderPromptHistory(prompts) {{
      historyList.textContent = "";
      if (!prompts.length) {{
        const empty = document.createElement("p");
        empty.className = "empty-history";
        empty.textContent = "No prompts saved yet.";
        historyList.appendChild(empty);
        return;
      }}

      for (const prompt of prompts) {{
        const item = document.createElement("article");
        item.className = "history-item";

        const text = document.createElement("p");
        text.className = "history-text";
        text.textContent = prompt;

        const actions = document.createElement("div");
        actions.className = "history-actions";

        const useButton = document.createElement("button");
        useButton.type = "button";
        useButton.textContent = "Use";
        useButton.addEventListener("click", () => {{
          promptInput.value = prompt;
          promptInput.focus();
          closeHistoryModal();
        }});

        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "danger";
        deleteButton.textContent = "Del";
        deleteButton.addEventListener("click", async () => {{
          deleteButton.disabled = true;
          const formData = new FormData();
          formData.append("prompt", prompt);
          const response = await fetch("/prompt-history/delete", {{
            method: "POST",
            body: formData,
          }});
          const data = await response.json();
          renderPromptHistory(data.prompts || []);
        }});

        actions.append(useButton, deleteButton);
        item.append(text, actions);
        historyList.appendChild(item);
      }}
    }}

    async function loadPromptHistory() {{
      const response = await fetch("/prompt-history");
      const data = await response.json();
      renderPromptHistory(data.prompts || []);
    }}

    function updateUpscalePlaceholder() {{
      const width = Number.parseInt(widthInput.value || "512", 10);
      const height = Number.parseInt(heightInput.value || "512", 10);
      const shortSide = Math.min(
        Number.isFinite(width) ? width : 512,
        Number.isFinite(height) ? height : 512
      );
      upscaleResolutionInput.placeholder = String(shortSide * 2);
    }}

    modelSelect.addEventListener("change", () => {{
      const defaults = modelDefaults[modelSelect.value] || modelDefaults.zimage;
      stepsInput.value = defaults.steps;
      filenamePrefixInput.value = defaults.filenamePrefix;
    }});

    widthInput.addEventListener("input", updateUpscalePlaceholder);
    heightInput.addEventListener("input", updateUpscalePlaceholder);
    updateUpscalePlaceholder();

    function renderFormErrors(errors) {{
      if (!errors.length) {{
        formErrors.textContent = "";
        return;
      }}

      const wrapper = document.createElement("div");
      wrapper.className = "alert error";
      const strong = document.createElement("strong");
      strong.textContent = "Fix these fields:";
      const list = document.createElement("ul");
      for (const error of errors) {{
        const item = document.createElement("li");
        item.textContent = error;
        list.appendChild(item);
      }}
      wrapper.append(strong, list);
      formErrors.textContent = "";
      formErrors.appendChild(wrapper);
    }}

    function resetGenerateButton() {{
      button.disabled = false;
      button.textContent = "Generate Image";
    }}

    function createProgressPanel() {{
      resultSlot.innerHTML = `
        <section class="progress-panel">
          <h2>Progress</h2>
          <div id="progress-result" class="progress-result"></div>
          <p id="progress-status" class="progress-status">Queued...</p>
          <div id="progress-log" class="progress-log" role="log" aria-live="polite"></div>
        </section>
      `;
    }}

    function appendProgressLine(message) {{
      const log = document.getElementById("progress-log");
      if (!log) {{
        return;
      }}
      log.textContent += `${{message}}\n`;
      log.scrollTop = log.scrollHeight;
    }}

    function setProgressStatus(message) {{
      const status = document.getElementById("progress-status");
      if (status) {{
        status.textContent = message;
      }}
    }}

    function connectJobStream(jobId) {{
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${{protocol}}://${{window.location.host}}/jobs/${{jobId}}/stream`);

      socket.addEventListener("message", (event) => {{
        const data = JSON.parse(event.data);
        if (data.type === "status") {{
          setProgressStatus(data.message || data.status || "Working...");
        }} else if (data.type === "log") {{
          const phase = data.phase ? `[${{data.phase}}] ` : "";
          if (data.stream === "command") {{
            appendProgressLine(`${{phase}}command started`);
            return;
          }}
          const stream = data.stream ? `${{data.stream}}: ` : "";
          appendProgressLine(`${{phase}}${{stream}}${{data.message || ""}}`);
        }} else if (data.type === "done" || data.type === "error") {{
          const target = document.getElementById("progress-result");
          if (target) {{
            target.innerHTML = data.result_html || "";
          }} else {{
            resultSlot.innerHTML = data.result_html || "";
          }}
          setProgressStatus(data.type === "done" ? "Finished." : "Finished with errors.");
          resetGenerateButton();
          socket.close();
        }}
      }});

      socket.addEventListener("close", () => {{
        if (button.disabled) {{
          appendProgressLine("Progress connection closed.");
          resetGenerateButton();
        }}
      }});

      socket.addEventListener("error", () => {{
        appendProgressLine("Progress connection error.");
        resetGenerateButton();
      }});
    }}

    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      renderFormErrors([]);
      button.disabled = true;
      button.textContent = "Generating...";
      createProgressPanel();

      const response = await fetch("/generate", {{
        method: "POST",
        body: new FormData(form),
      }});
      const data = await response.json();
      if (!response.ok || data.errors) {{
        renderFormErrors(data.errors || ["Generation could not start."]);
        resultSlot.innerHTML = `<section class="result"><h2>Result</h2><p class="meta">Generated images will appear here after the command finishes.</p></section>`;
        resetGenerateButton();
        return;
      }}

      connectJobStream(data.job_id);
    }});

    historyButton.addEventListener("click", openHistoryModal);
    historyClose.addEventListener("click", closeHistoryModal);
    historyModal.addEventListener("click", (event) => {{
      if (event.target === historyModal) {{
        closeHistoryModal();
      }}
    }});
    document.addEventListener("keydown", (event) => {{
      if (event.key === "Escape") {{
        closeHistoryModal();
      }}
    }});
  </script>
</body>
</html>"""
    return document


def render_result(result: dict[str, object] | None, values: dict[str, object]) -> str:
    if not result:
        return """<section class="result">
      <h2>Result</h2>
      <p class="meta">Generated images will appear here after the command finishes.</p>
    </section>"""

    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    command = result.get("command", [])
    command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command)
    output_path = result.get("output_path", "")

    if result.get("success"):
        image_url = html.escape(str(result.get("image_url", "")))
        upscale_html = render_upscale_result(result.get("upscale"))
        return f"""<section class="result">
      <h2>Result</h2>
      <div class="alert ok">Image generated successfully.</div>
      <p class="meta"><strong>Model:</strong> {html.escape(str(values.get("model", "")))}</p>
      <p class="meta"><strong>Seed:</strong> {html.escape(str(values.get("seed", "")))}</p>
      <p class="meta"><strong>Output:</strong> {html.escape(str(output_path))}</p>
      <img src="{image_url}" alt="Generated image">
      {upscale_html}
      {render_log("Generate Command", command_text)}
    </section>"""

    return f"""<section class="result">
      <h2>Result</h2>
      <div class="alert error">{html.escape(str(result.get("error", "Generation failed.")))}</div>
      <p class="meta"><strong>Seed:</strong> {html.escape(str(values.get("seed", "")))}</p>
      {render_log("Generate Command", command_text)}
      {render_log("Generate Output", stdout)}
      {render_log("Generate Errors", stderr)}
    </section>"""


def render_upscale_result(upscale: object) -> str:
    if not isinstance(upscale, dict):
        return ""

    stdout = str(upscale.get("stdout", "")).strip()
    stderr = str(upscale.get("stderr", "")).strip()
    command = upscale.get("command", [])
    command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command)

    if upscale.get("success"):
        image_url = html.escape(str(upscale.get("image_url", "")))
        return f"""
      <h3>Upscaled Result</h3>
      <div class="alert ok">Image upscaled successfully.</div>
      <p class="meta"><strong>Resolution:</strong> {html.escape(str(upscale.get("resolution", "")))}</p>
      <p class="meta"><strong>Output:</strong> {html.escape(str(upscale.get("output_path", "")))}</p>
      <img src="{image_url}" alt="Upscaled generated image">
      {render_log("Upscale Command", command_text)}"""

    return f"""
      <h3>Upscaled Result</h3>
      <div class="alert error">{html.escape(str(upscale.get("error", "Upscale failed.")))}</div>
      {render_log("Upscale Command", command_text)}
      {render_log("Upscale Output", stdout)}
      {render_log("Upscale Errors", stderr)}"""


def render_log(title: str, text: str) -> str:
    if not text:
        return ""
    return f"<h3>{html.escape(title)}</h3><pre>{html.escape(text)}</pre>"


@app.get("/")
async def index() -> Response:
    return Response(page(), content_type="text/html; charset=utf-8")


@app.post("/generate")
async def generate():
    form_data = await request.form
    form = {key: form_data.get(key, "").strip() for key in form_data}
    values, errors = validate_form(form)
    if errors:
        return jsonify({"errors": errors}), 400

    job_id = uuid.uuid4().hex
    job: dict[str, object] = {
        "id": job_id,
        "status": "queued",
        "values": values,
        "messages": [],
        "queue": asyncio.Queue(),
    }
    JOBS[job_id] = job
    await set_job_status(job, "queued", "queued", "Queued...")
    asyncio.create_task(run_job(job_id))
    return jsonify({"job_id": job_id})


@app.websocket("/jobs/<job_id>/stream")
async def job_stream(job_id: str) -> None:
    job = JOBS.get(job_id)
    if job is None:
        await websocket.send_json(
            {
                "type": "error",
                "status": "error",
                "phase": "error",
                "message": "Job not found.",
                "result_html": render_result(
                    {
                        "success": False,
                        "error": "Job not found.",
                        "stdout": "",
                        "stderr": "",
                        "command": [],
                    },
                    {},
                ),
            }
        )
        return

    cursor = 0
    queue = job.get("queue")
    while True:
        messages = job.get("messages", [])
        if isinstance(messages, list):
            while cursor < len(messages):
                message = messages[cursor]
                cursor += 1
                await websocket.send_json(message)
                if isinstance(message, dict) and message.get("type") in {"done", "error"}:
                    return

        if isinstance(queue, asyncio.Queue):
            await queue.get()
        else:
            await asyncio.sleep(0.25)


@app.get("/prompt-history")
async def prompt_history():
    prompts = await asyncio.to_thread(load_prompt_history)
    return jsonify({"prompts": prompts})


@app.post("/prompt-history/delete")
async def prompt_history_delete():
    form_data = await request.form
    prompts = await asyncio.to_thread(delete_prompt_history, form_data.get("prompt", ""))
    return jsonify({"prompts": prompts})


@app.get("/outputs/<path:filename>")
async def output_file(filename: str):
    if "/" in filename or "\\" in filename:
        abort(404)

    path = (OUTPUTS_DIR / Path(filename).name).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if outputs_root not in path.parents or not path.exists() or not path.is_file():
        abort(404)

    return await send_file(path)


def main() -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    app.run(host=HOST, port=PORT)


if __name__ == "__main__":
    main()
