from __future__ import annotations

import asyncio
import html
import json
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path

from quart import Quart, Response, abort, request, send_file


ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "outputs"
HOST = "127.0.0.1"
PORT = 5002
app = Quart(__name__)

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
}

SAFE_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def field(form: dict[str, str], name: str, default: str = "") -> str:
    return form.get(name, default).strip()


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


def validate_form(form: dict[str, str]) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    model = field(form, "model", "zimage")
    prompt = field(form, "prompt")
    random_seed = "random_seed" in form

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
    }
    return values, errors


def run_generation(values: dict[str, object]) -> dict[str, object]:
    model_name = str(values["model"])
    model = MODELS[model_name]
    command_path = Path(model["command"])

    if not command_path.exists():
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
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "success": False,
            "error": str(exc),
            "stdout": "",
            "stderr": "",
            "command": command,
        }

    success = completed.returncode == 0 and output_path.exists()
    return {
        "success": success,
        "error": "" if success else f"Generation failed with exit code {completed.returncode}.",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "command": command,
        "output_path": output_path,
        "image_url": f"/outputs/{output_path.name}" if success else "",
    }


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
      <h1>Local Image Generator</h1>
      {error_html}
      <form id="generator-form" method="post" action="/generate">
        <label for="model">Model</label>
        <select id="model" name="model">{model_options}</select>

        <label for="prompt">Prompt</label>
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

        <label for="filename_prefix">Output filename prefix</label>
        <input id="filename_prefix" name="filename_prefix" value="{html.escape(str(values["filename_prefix"]))}" placeholder="zimage">

        <button id="generate-button" type="submit">Generate Image</button>
      </form>
    </section>
    {result_html}
  </main>
  <script>
    const modelDefaults = {client_defaults_json};
    const modelSelect = document.getElementById("model");
    const stepsInput = document.getElementById("steps");
    const filenamePrefixInput = document.getElementById("filename_prefix");
    const form = document.getElementById("generator-form");
    const button = document.getElementById("generate-button");

    modelSelect.addEventListener("change", () => {{
      const defaults = modelDefaults[modelSelect.value] || modelDefaults.zimage;
      stepsInput.value = defaults.steps;
      filenamePrefixInput.value = defaults.filenamePrefix;
    }});

    form.addEventListener("submit", () => {{
      button.disabled = true;
      button.textContent = "Generating...";
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
        return f"""<section class="result">
      <h2>Result</h2>
      <div class="alert ok">Image generated successfully.</div>
      <p class="meta"><strong>Model:</strong> {html.escape(str(values["model"]))}</p>
      <p class="meta"><strong>Seed:</strong> {html.escape(str(values["seed"]))}</p>
      <p class="meta"><strong>Output:</strong> {html.escape(str(output_path))}</p>
      <img src="{image_url}" alt="Generated image">
      {render_log("Command", command_text)}
      {render_log("Output", stdout)}
      {render_log("Errors", stderr)}
    </section>"""

    return f"""<section class="result">
      <h2>Result</h2>
      <div class="alert error">{html.escape(str(result.get("error", "Generation failed.")))}</div>
      <p class="meta"><strong>Seed:</strong> {html.escape(str(values["seed"]))}</p>
      {render_log("Command", command_text)}
      {render_log("Output", stdout)}
      {render_log("Errors", stderr)}
    </section>"""


def render_log(title: str, text: str) -> str:
    if not text:
        return ""
    return f"<h3>{html.escape(title)}</h3><pre>{html.escape(text)}</pre>"


@app.get("/")
async def index() -> Response:
    return Response(page(), content_type="text/html; charset=utf-8")


@app.post("/generate")
async def generate() -> Response:
    form_data = await request.form
    form = {key: form_data.get(key, "").strip() for key in form_data}
    values, errors = validate_form(form)
    result = None if errors else await asyncio.to_thread(run_generation, values)
    return Response(page(values=values, result=result, errors=errors), content_type="text/html; charset=utf-8")


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
