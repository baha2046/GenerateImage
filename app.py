from __future__ import annotations

import asyncio
import html
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path

from quart import Quart, Response, abort, jsonify, render_template, request, send_file, send_from_directory, websocket

ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = ROOT / "outputs"
PROMPT_HISTORY_PATH = ROOT / "prompt_history.json"
FORM_STATE_PATH = ROOT / "form_state.json"
UI_SETTINGS_PATH = ROOT / "ui_settings.json"
PROMPT_TEMPLATES_PATH = ROOT / "prompt_templates.json"
MAX_PROMPT_HISTORY = 100
MIN_DIMENSION = 64
MAX_DIMENSION = 2048
HOST = "127.0.0.1"
PORT = 5002
app = Quart(__name__)
# Jinja2 templates configured for UI renewal (Phase C). templates/ dir contains
# base.html + components. Quart auto-discovers ./templates when jinja2 is installed.
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True

JOBS: dict[str, dict[str, object]] = {}
MAX_COMPLETED_JOBS = 20

# Static file serving for extracted CSS/JS (Phase B)
@app.route("/static/<path:filename>")
async def static_files(filename: str):
    return await send_from_directory("static", filename)

MODELS = {
    "zimage": {
        "label": "Z-Image Turbo",
        "command": ROOT / ".venv/bin/mflux-generate-z-image-turbo",
        "extra_args": [
            "--model", "carsenk/z-image-turbo-mflux-8bit",
            "--lora-paths", "/Users/ericchan/Project/image/lora/NSFW_master_ZIT_000017532.safetensors",
            "--lora-scales", "0.8",
        ],
        "default_steps": 9,
        "filename_prefix": "zimage",
    },
    "zimage-base": {
        "label": "Z-Image",
        "command": ROOT / ".venv/bin/mflux-generate-z-image",
        "extra_args": [
            "--model", "deepsweet/Z-Image-6B-MLX-Q8",
            "--guidance", "4",
        ],
        "default_steps": 50,
        "filename_prefix": "zimage",
    },
    "flux2": {
        "label": "Flux 2 Klein 4B",
        "command": ROOT / ".venv/bin/mflux-generate-flux2",
        "extra_args": [
            "--model", "flux2-klein-4b",
            "-q", "8",
        ],
        "default_steps": 4,
        "filename_prefix": "flux",
    },
    "flux2-9B": {
        "label": "Flux 2 Klein 9B 4bit",
        "command": ROOT / ".venv/bin/mflux-generate-flux2",
        "extra_args": [
            "--model", "AITRADER/FLUX2-klein-9B-mlx-4bit",
            "--base-model", "flux2-klein-9b",
            "--guidance", "1.0",
        ],
        "default_steps": 4,
        "filename_prefix": "flux",
    },
    "flux2-9B-lora": {
        "label": "Flux 2 Klein 9B LORA",
        "command": ROOT / ".venv/bin/mflux-generate-flux2",
        "extra_args": [
            "--model", "AITRADER/FLUX2-klein-9B-mlx-4bit",
            "--base-model", "flux2-klein-9b",
            "--lora-paths", "/Users/ericchan/Project/image/lora/Flux%20Klein%20-%20NSFW%20v2.safetensors",
            "--lora-scales", "0.7",
        ],
        "default_steps": 20,
        "filename_prefix": "flux",
    },
    "flux2-9B-face": {
        "label": "Flux 2 Klein 9B 4bit Face",
        "command": ROOT / ".venv/bin/mflux-generate-flux2-edit",
        "extra_args": [
            "--model", "AITRADER/FLUX2-klein-9B-mlx-4bit",
            "--base-model", "flux2-klein-9b",
            "--image-paths", "face.png",
            "--guidance", "1.0",
        ],
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
            "-q", "8",
        ],
        "default_steps": 8,
        "filename_prefix": "qwen",
    },
    "qwen-2512": {
        "label": "Qwen Image 2512 4bit",
        "command": ROOT / ".venv/bin/mflux-generate-qwen",
        "extra_args": [
            "--model", "machiabeli/Qwen-Image-2512-4bit-MLX",
        ],
        "default_steps": 20,
        "filename_prefix": "qwen",
    },
}

SAFE_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


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


# === Prompt Templates (richer saved presets) ===

def load_prompt_templates() -> list[dict]:
    try:
        data = json.loads(PROMPT_TEMPLATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    templates: list[dict] = []
    seen_names: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in seen_names:
            continue
        templates.append(item)
        seen_names.add(name)
    return templates


def save_prompt_templates(templates: list[dict]) -> None:
    # Keep it simple and defensive
    normalized = []
    seen = set()
    for t in templates:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name", "")).strip()
        if not name or name in seen:
            continue
        normalized.append(t)
        seen.add(name)

    PROMPT_TEMPLATES_PATH.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")


def add_prompt_template(template: dict) -> list[dict]:
    templates = load_prompt_templates()

    name = str(template.get("name", "")).strip()
    if not name:
        return templates

    # Remove existing with same name (overwrite on save)
    templates = [t for t in templates if str(t.get("name", "")).strip().lower() != name.lower()]
    templates.insert(0, template)

    save_prompt_templates(templates)
    return templates


def delete_prompt_template(name: str) -> list[dict]:
    cleaned = name.strip()
    templates = [t for t in load_prompt_templates() if str(t.get("name", "")).strip() != cleaned]
    save_prompt_templates(templates)
    return templates


def rename_prompt_template(old_name: str, new_name: str) -> list[dict]:
    old = old_name.strip()
    new = new_name.strip()

    if not old or not new:
        return load_prompt_templates()

    templates = load_prompt_templates()

    # Find the template to rename
    target = None
    for t in templates:
        if str(t.get("name", "")).strip() == old:
            target = t
            break

    if not target:
        return templates

    # Check if new name already exists (we'll overwrite the old one, but prevent conflict)
    existing_new = any(
        str(t.get("name", "")).strip().lower() == new.lower() and str(t.get("name", "")).strip() != old
        for t in templates
    )
    if existing_new:
        # Simple behavior: don't allow rename to existing name
        return templates

    # Perform rename
    target["name"] = new

    # Remove any duplicate with the exact new name (defensive)
    templates = [t for t in templates if str(t.get("name", "")).strip() != new or t is target]

    save_prompt_templates(templates)
    return templates


def validate_dimension(value: object, name: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a whole number.") from exc

    if parsed < MIN_DIMENSION or parsed > MAX_DIMENSION:
        raise ValueError(f"{name} must be between {MIN_DIMENSION} and {MAX_DIMENSION}.")
    return parsed


def load_form_state() -> dict[str, int]:
    fallback = {"width": 512, "height": 512}
    try:
        data = json.loads(FORM_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

    if not isinstance(data, dict):
        return fallback

    try:
        return {
            "width": validate_dimension(data.get("width", fallback["width"]), "Width"),
            "height": validate_dimension(data.get("height", fallback["height"]), "Height"),
        }
    except ValueError:
        return fallback


def save_form_dimensions(width: int, height: int) -> dict[str, int]:
    state = {
        "width": validate_dimension(width, "Width"),
        "height": validate_dimension(height, "Height"),
    }
    FORM_STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def load_ui_settings() -> dict[str, object]:
    defaults = {
        "theme": "system",                 # "light" | "dark" | "system"
        "default_model": "zimage",
        "auto_open_gallery_on_success": False,
        "show_advanced_by_default": False,
    }
    try:
        data = json.loads(UI_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults

    if not isinstance(data, dict):
        return defaults

    return {
        "theme": data.get("theme", defaults["theme"]),
        "default_model": data.get("default_model", defaults["default_model"]),
        "auto_open_gallery_on_success": bool(data.get("auto_open_gallery_on_success", defaults["auto_open_gallery_on_success"])),
        "show_advanced_by_default": bool(data.get("show_advanced_by_default", defaults["show_advanced_by_default"])),
    }


def save_ui_settings(settings: dict[str, object]) -> dict[str, object]:
    cleaned = {
        "theme": settings.get("theme", "system"),
        "default_model": settings.get("default_model", "zimage"),
        "auto_open_gallery_on_success": bool(settings.get("auto_open_gallery_on_success", False)),
        "show_advanced_by_default": bool(settings.get("show_advanced_by_default", False)),
    }
    UI_SETTINGS_PATH.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")
    return cleaned


def format_file_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def safe_output_image_path(filename: str) -> Path:
    clean_name = filename.strip()
    if not clean_name or "/" in clean_name or "\\" in clean_name or clean_name != Path(clean_name).name:
        raise ValueError("Invalid image filename.")

    path = (OUTPUTS_DIR / clean_name).resolve()
    outputs_root = OUTPUTS_DIR.resolve()
    if outputs_root not in path.parents or path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Invalid image filename.")
    return path


def metadata_path_for_image(path: Path) -> Path:
    return path.with_name(f"{path.name}.meta.json")


def build_generation_metadata(values: dict[str, object], result: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {
        "version": 1,
        "kind": "generation",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "filename": Path(str(result.get("output_path", values.get("filename", "")))).name,
        "prompt": str(values.get("prompt", "")),
        "model": str(values.get("model", "")),
        "seed": values.get("seed"),
        "steps": values.get("steps"),
        "size": {
            "width": values.get("width"),
            "height": values.get("height"),
        },
        "filename_prefix": str(values.get("filename_prefix", "")),
        "random_seed": bool(values.get("random_seed")),
        "upscale_enabled": bool(values.get("upscale_enabled")),
        "upscale_resolution": values.get("upscale_resolution"),
    }

    for key in ("guidance", "lora_scale", "negative_prompt"):
        if values.get(key) is not None:
            metadata[key] = values.get(key)

    if result.get("image_url"):
        metadata["image_url"] = str(result.get("image_url"))

    return metadata


def build_upscale_metadata(source_path: Path, result: dict[str, object], resolution: int) -> dict[str, object]:
    source_metadata = read_image_metadata(source_path)
    metadata = dict(source_metadata) if isinstance(source_metadata, dict) else {
        "version": 1,
        "kind": "upscale",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    output_path = Path(str(result.get("output_path", "")))
    metadata.update(
        {
            "version": 1,
            "filename": output_path.name,
            "image_url": str(result.get("image_url", "")),
            "upscale_enabled": True,
            "upscale_resolution": resolution,
            "upscale": {
                "enabled": True,
                "resolution": resolution,
                "source_filename": source_path.name,
                "source_url": f"/outputs/{source_path.name}",
            },
        }
    )
    return metadata


def write_image_metadata(path: Path, metadata: dict[str, object]) -> None:
    sidecar = metadata_path_for_image(path)
    tmp_path = sidecar.with_name(f"{sidecar.name}.tmp")
    tmp_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(sidecar)


def read_image_metadata(path: Path) -> dict[str, object] | None:
    sidecar = metadata_path_for_image(path)
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_output_images() -> list[dict[str, object]]:
    if not OUTPUTS_DIR.exists():
        return []

    images: list[dict[str, object]] = []
    for path in OUTPUTS_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        stat = path.stat()
        name = path.name
        lower = name.lower()

        # Derive filter-friendly metadata from filename convention
        is_upscaled = lower.startswith("upscaled-")
        base = name[9:] if is_upscaled else name  # strip "upscaled-" prefix if present
        prefix = base.split("-", 1)[0] if "-" in base else "other"

        images.append(
            {
                "filename": name,
                "url": f"/outputs/{name}",
                "size": stat.st_size,
                "size_label": format_file_size(stat.st_size),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                "prefix": prefix,               # e.g. "flux", "zimage", "qwen"
                "is_upscaled": is_upscaled,
                "metadata": read_image_metadata(path),
            }
        )

    images.sort(key=lambda item: str(item["modified"]), reverse=True)
    return images


def delete_output_image(filename: str) -> list[dict[str, object]]:
    path = safe_output_image_path(filename)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Image file not found.")
    path.unlink()
    metadata_path = metadata_path_for_image(path)
    if metadata_path.exists():
        metadata_path.unlink()
    return list_output_images()


def parse_int(value: str, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number.") from exc

    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return parsed


def clamp_dimension(value: int) -> int:
    return max(MIN_DIMENSION, min(MAX_DIMENSION, value))


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
        width = validate_dimension(field(form, "width", "512"), "Width")
    except ValueError as exc:
        errors.append(str(exc))
        width = 512

    try:
        height = validate_dimension(field(form, "height", "512"), "Height")
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

    # Advanced parameters (optional, only passed through if user provided non-empty values)
    guidance_raw = field(form, "guidance")
    lora_scale_raw = field(form, "lora_scale")
    negative_prompt = field(form, "negative_prompt")

    guidance = None
    if guidance_raw:
        try:
            g = float(guidance_raw)
            if 0 <= g <= 20:
                guidance = g
            else:
                errors.append("Guidance must be between 0 and 20.")
        except ValueError:
            errors.append("Guidance must be a number.")

    lora_scale = None
    if lora_scale_raw:
        try:
            ls = float(lora_scale_raw)
            if 0 <= ls <= 2:
                lora_scale = ls
            else:
                errors.append("LoRA scale must be between 0 and 2.")
        except ValueError:
            errors.append("LoRA scale must be a number.")

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
        "guidance": guidance,
        "lora_scale": lora_scale,
        "negative_prompt": negative_prompt or None,
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

    # Store the process so we can cancel it later
    job["_process"] = process

    stdout: list[str] = []
    stderr: list[str] = []
    await asyncio.gather(
        collect_process_stream(process.stdout, "stdout", phase, job, stdout),
        collect_process_stream(process.stderr, "stderr", phase, job, stderr),
    )
    return_code = await process.wait()

    # Clear process reference when done
    job.pop("_process", None)

    return return_code, stdout, stderr


async def cancel_job(job: dict[str, object]) -> bool:
    """Attempt to cancel a running job by killing its subprocess."""
    process = job.get("_process")
    if process and process.returncode is None:
        try:
            process.kill()
            job["status"] = "cancelled"
            await emit_job_message(
                job,
                {
                    "type": "error",
                    "status": "cancelled",
                    "phase": "cancelled",
                    "message": "Generation cancelled by user.",
                },
            )
            job.pop("_process", None)
            return True
        except Exception:
            return False
    return False


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
    result = {
        "success": success,
        "error": "" if success else f"Upscale failed with exit code {return_code}.",
        "stdout": "\n".join(stdout),
        "stderr": "\n".join(stderr),
        "command": command,
        "output_path": output_path,
        "image_url": f"/outputs/{output_path.name}" if success else "",
        "resolution": resolution,
    }
    if success:
        write_image_metadata(output_path, build_upscale_metadata(image_path, result, resolution))
    return result


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
    ]

    # Advanced parameters (only added when user explicitly provided values)
    if values.get("guidance") is not None:
        command.extend(["--guidance", str(values["guidance"])])

    if values.get("lora_scale") is not None:
        command.extend(["--lora-scales", str(values["lora_scale"])])

    if values.get("negative_prompt"):
        command.extend(["--negative-prompt", str(values["negative_prompt"])])

    command.extend(["--output", str(output_path)])

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
    result = {
        "success": success,
        "error": "" if success else f"Generation failed with exit code {return_code}.",
        "stdout": "\n".join(stdout),
        "stderr": "\n".join(stderr),
        "command": command,
        "output_path": output_path,
        "image_url": f"/outputs/{output_path.name}" if success else "",
    }
    if success:
        write_image_metadata(output_path, build_generation_metadata(values, result))
    return result


async def run_generation_with_optional_upscale(values: dict[str, object], job: dict[str, object]) -> dict[str, object]:
    await set_job_status(job, "generating", "generating", "Generating image...")
    result = await run_generation(values, job)
    if not result.get("success") or not values.get("upscale_enabled"):
        return result

    await set_job_status(job, "upscaling", "upscaling", "Upscaling image...")
    result["upscale"] = await run_upscale(Path(result["output_path"]), int(values["upscale_resolution"]), job)
    return result


async def run_upscale_only(job_id: str, image_path: Path, resolution: int) -> None:
    """Standalone upscale job (triggered from gallery)."""
    job = JOBS.get(job_id)
    if not job:
        return
    try:
        await set_job_status(job, "upscaling", "upscaling", f"Upscaling {image_path.name}...")
        result = await run_upscale(image_path, resolution, job)
        job["result"] = result
        status = "done" if result.get("success") else "error"

        # Lightweight result card for standalone upscales
        if result.get("success"):
            upscaled_url = result.get("image_url", "")
            final_html = f"""
            <section class="result">
              <h2>Upscale Complete</h2>
              <div class="alert ok">Image upscaled successfully to {resolution}px.</div>
              <p class="meta"><strong>Source:</strong> {html.escape(str(image_path.name))}</p>
              <p class="meta"><strong>Output:</strong> {html.escape(str(result.get("output_path", "")))}</p>
              <img src="{html.escape(upscaled_url)}" alt="Upscaled image">
            </section>
            """
        else:
            final_html = f"""
            <section class="result">
              <h2>Upscale Failed</h2>
              <div class="alert error">{html.escape(str(result.get("error", "Unknown error")))}</div>
            </section>
            """

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
        await emit_job_message(
            job,
            {
                "type": "error",
                "status": "error",
                "phase": "error",
                "message": str(exc),
                "result_html": f'<section class="result"><div class="alert error">{html.escape(str(exc))}</div></section>',
            },
        )
    finally:
        prune_completed_jobs()


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


def svg_icon(name: str) -> str:
    icons = {
        "history": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 7v5l3 2"/></svg>',
        "image": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10.5" r="1.5"/><path d="m21 15-5-5L5 19"/></svg>',
        "check": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m20 6-11 11-5-5"/></svg>',
        "external": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>',
        "rename": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
        "trash": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/><path d="M10 11v5"/><path d="M14 11v5"/></svg>',
        "close": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
        "upscale": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17h4v4"/><path d="m7 17-4 4"/><path d="M21 7h-4V3"/><path d="m17 7 4-4"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>',
        "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5A3.5 3.5 0 0 1 8.5 12 3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5 3.5 3.5 0 0 1-3.5 3.5"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    }
    return icons.get(name, "")


# Expose to Jinja templates (Phase C renewal)
app.jinja_env.globals["svg_icon"] = svg_icon
app.jinja_env.globals["MIN_DIMENSION"] = MIN_DIMENSION
app.jinja_env.globals["MAX_DIMENSION"] = MAX_DIMENSION


def get_static_version(filename: str) -> str:
    """Return a cache-busting query string based on file mtime (great for dev)."""
    try:
        path = ROOT / "static" / filename
        if path.exists():
            mtime = int(path.stat().st_mtime)
            return f"?v={mtime}"
    except Exception:
        pass
    return ""


def page(values: dict[str, object] | None = None, result: dict[str, object] | None = None, errors: list[str] | None = None) -> str:
    saved_dimensions = load_form_state()
    values = values or {
        "model": "zimage",
        "prompt": "A puffin standing on a cliff",
        "width": saved_dimensions["width"],
        "height": saved_dimensions["height"],
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

    # Cache-busting versions for static assets (prevents stale JS/CSS in browsers like Edge)
    js_version = get_static_version("app.js")
    css_version = get_static_version("app.css")

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

    # Pre-build the small client config script outside the giant f-string to avoid
    # brace-escaping / NameError issues with embedded JS object literals.
    config_script = f'''<script>
    window.APP_CONFIG = {{
      modelDefaults: {client_defaults_json},
      icons: {{
        check: `{svg_icon("check")}`,
        external: `{svg_icon("external")}`,
        rename: `{svg_icon("rename")}`,
        trash: `{svg_icon("trash")}`,
        upscale: `{svg_icon("upscale")}`,
      }}
    }};
  </script>'''

    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Local Image Generator</title>
  <link rel="stylesheet" href="/static/app.css{css_version}">
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
          <div class="history-actions">
            <button id="history-button" class="secondary icon-button" type="button" aria-label="Prompt History" title="Prompt History">{svg_icon("history")}</button>
            <button id="templates-button" class="secondary icon-button" type="button" aria-label="Prompt Templates" title="Prompt Templates">★</button>
            <button id="outputs-button" class="secondary icon-button" type="button" aria-label="Output Images" title="Output Images">{svg_icon("image")}</button>
            <button id="settings-button" class="secondary icon-button" type="button" aria-label="Settings" title="Settings">{svg_icon("settings")}</button>
          </div>
        </div>
        <textarea id="prompt" name="prompt" required>{html.escape(str(values["prompt"]))}</textarea>

        <div class="grid">
          <div>
            <label for="width">Width</label>
            <div class="dimension-row">
              <input id="width" class="dimension-input" name="width" type="number" min="{MIN_DIMENSION}" max="{MAX_DIMENSION}" step="1" value="{html.escape(str(values["width"]))}">
              <button class="dimension-action" data-dimension="width" data-factor="2" type="button" aria-label="Double width" title="Double width">x2</button>
              <button class="dimension-action" data-dimension="width" data-factor="0.5" type="button" aria-label="Halve width" title="Halve width">/2</button>
            </div>
          </div>
          <div>
            <label for="height">Height</label>
            <div class="dimension-row">
              <input id="height" class="dimension-input" name="height" type="number" min="{MIN_DIMENSION}" max="{MAX_DIMENSION}" step="1" value="{html.escape(str(values["height"]))}">
              <button class="dimension-action" data-dimension="height" data-factor="2" type="button" aria-label="Double height" title="Double height">x2</button>
              <button class="dimension-action" data-dimension="height" data-factor="0.5" type="button" aria-label="Halve height" title="Halve height">/2</button>
            </div>
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

        <details class="advanced-section">
          <summary>Advanced parameters</summary>
          <div class="advanced-content">

            <div class="advanced-field" data-for-models="zimage-base,flux2-9B,flux2-9B-lora,flux2-9B-face">
              <label for="guidance">Guidance</label>
              <input id="guidance" name="guidance" type="number" step="0.1" min="0" max="20" placeholder="auto">
            </div>

            <div class="advanced-field" data-for-models="zimage,zimage-base,flux2-9B-lora,qwen">
              <label for="lora_scale">LoRA Scale</label>
              <input id="lora_scale" name="lora_scale" type="number" step="0.05" min="0" max="2" placeholder="auto">
            </div>

            <div class="advanced-field" data-for-models="qwen,qwen-2512">
              <label for="negative_prompt">Negative Prompt</label>
              <textarea id="negative_prompt" name="negative_prompt" rows="2" placeholder="Leave empty to use model default"></textarea>
            </div>

          </div>
        </details>

        <button id="generate-button" type="submit">Generate Image</button>
      </form>
    </section>
    <div id="result-slot">{result_html}</div>
  </main>
  {render_history_modal()}
  {render_templates_modal()}
  {render_outputs_modal()}
  {render_settings_modal()}
  {render_compare_modal()}

  {config_script}
  <script src="/static/app.js{js_version}"></script>
</body>
</html>"""
    # Phase C (renewal): we still build the giant string above for perfect 1:1 during port.
    # Next commit in this step will switch fully to render_template + extracted partials.
    # For now keep returning the trusted HTML so the live UI is untouched.
    return document


def render_result(result: dict[str, object] | None, values: dict[str, object]) -> str:
    if not result:
        return """<section class="result bg-white dark:bg-[#1a201f] border border-[#d9dedb] dark:border-[#33413d] rounded-2xl p-8 text-center shadow-sm">
      <div class="mx-auto mb-3 h-12 w-12 rounded-2xl bg-[#f7f7f4] dark:bg-[#111514] flex items-center justify-center">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[#0f766e]"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10.5" r="1.5"/><path d="m21 15-5-5L5 19"/></svg>
      </div>
      <div class="font-semibold text-lg mb-1">No image yet</div>
      <p class="text-sm text-[#626b73] dark:text-[#a7b1ad]">Your generated images will appear here after you hit Generate.</p>
    </section>"""

    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    command = result.get("command", [])
    command_text = " ".join(str(part) for part in command) if isinstance(command, list) else str(command)
    output_path = result.get("output_path", "")

    if result.get("success"):
        image_url = html.escape(str(result.get("image_url", "")))
        upscale_html = render_upscale_result(result.get("upscale"))

        result_data = {
            "model": str(values.get("model", "")),
            "prompt": str(values.get("prompt", "")),
            "width": values.get("width"),
            "height": values.get("height"),
            "steps": values.get("steps"),
            "seed": values.get("seed"),
            "random_seed": bool(values.get("random_seed")),
            "filename_prefix": str(values.get("filename_prefix", "")),
            "upscale_enabled": bool(values.get("upscale_enabled")),
            "upscale_resolution": values.get("upscale_resolution"),
            "guidance": values.get("guidance"),
            "lora_scale": values.get("lora_scale"),
            "negative_prompt": values.get("negative_prompt"),
            "image_url": str(result.get("image_url", "")),
            "upscaled_image_url": str(result.get("upscale", {}).get("image_url", "")) if result.get("upscale") and result.get("upscale").get("success") else "",
        }
        result_data_json = html.escape(json.dumps(result_data), quote=True)

        has_upscale = bool(result.get("upscale") and result.get("upscale").get("success"))
        compare_button = '<button type="button" class="px-3 py-1.5 text-xs font-medium rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514]" data-action="compare">Compare</button>' if has_upscale else ''

        action_html = (
            '<div class="result-actions flex flex-wrap gap-2 mt-4">'
            '<button type="button" class="px-3 py-1.5 text-xs font-medium rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514]" data-action="remix">Remix (same)</button>'
            '<button type="button" class="px-3 py-1.5 text-xs font-medium rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514]" data-action="remix-new-seed">Remix (new seed)</button>'
            '<button type="button" class="px-3 py-1.5 text-xs font-medium rounded-xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-[#f7f7f4] dark:hover:bg-[#111514]" data-action="copy-prompt">Copy Prompt</button>'
            + compare_button +
            '</div>'
        )

        # Renewed Tailwind result card (matches new form style)
        # Keep the "result" class for backward compatibility with existing JS handlers
        return f"""<section class="result bg-white dark:bg-[#1a201f] border border-[#d9dedb] dark:border-[#33413d] rounded-2xl p-6 shadow-sm" data-result="{result_data_json}">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-semibold tracking-tight">Result</h2>
        <div class="px-3 py-1 text-xs rounded-full bg-[#eefbf4] dark:bg-[#123225] text-[#17633a] dark:text-[#a8f0c9] font-medium">Success</div>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2 text-sm mb-4">
        <div><span class="text-[#626b73] dark:text-[#a7b1ad]">Model</span><br><span class="font-medium">{html.escape(str(values.get("model", "")))}</span></div>
        <div><span class="text-[#626b73] dark:text-[#a7b1ad]">Seed</span><br><span class="font-medium">{html.escape(str(values.get("seed", "")))}</span></div>
        <div class="sm:col-span-2"><span class="text-[#626b73] dark:text-[#a7b1ad]">Output</span><br><span class="font-mono text-xs break-all">{html.escape(str(output_path))}</span></div>
      </div>

      {action_html}

      <div class="mt-4 rounded-2xl overflow-hidden border border-[#d9dedb] dark:border-[#33413d]">
        <img src="{image_url}" alt="Generated image" class="w-full">
      </div>

      {upscale_html}
      {render_log("Generate Command", command_text)}
    </section>"""

    return f"""<section class="result bg-white dark:bg-[#1a201f] border border-red-200 dark:border-red-900/60 rounded-2xl p-6 shadow-sm">
      <div class="flex items-center gap-3 mb-4">
        <div class="px-3 py-1 text-xs rounded-full bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-400 font-medium">Error</div>
        <h2 class="text-xl font-semibold tracking-tight">Result</h2>
      </div>
      <div class="alert error">{html.escape(str(result.get("error", "Generation failed.")))}</div>
      <p class="text-sm text-[#626b73] dark:text-[#a7b1ad] mb-4"><strong>Seed:</strong> {html.escape(str(values.get("seed", "")))}</p>
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
      <div class="mt-6 pt-6 border-t border-[#d9dedb] dark:border-[#33413d]">
        <div class="flex items-center justify-between mb-3">
          <div class="font-semibold">Upscaled Result</div>
          <div class="text-xs px-2.5 py-0.5 rounded-full bg-[#eefbf4] dark:bg-[#123225] text-[#17633a] dark:text-[#a8f0c9]">Upscaled</div>
        </div>
        <div class="text-sm mb-3 text-[#626b73] dark:text-[#a7b1ad]">
          Resolution: <span class="font-medium text-[#1e2428] dark:text-[#edf3f1]">{html.escape(str(upscale.get("resolution", "")))}px</span>
        </div>
        <div class="rounded-2xl overflow-hidden border border-[#d9dedb] dark:border-[#33413d]">
          <img src="{image_url}" alt="Upscaled generated image" class="w-full">
        </div>
        {render_log("Upscale Command", command_text)}
      </div>"""

    return f"""
      <div class="mt-6 pt-6 border-t border-red-200 dark:border-red-900/60">
        <div class="font-semibold mb-2 text-red-600 dark:text-red-400">Upscale Failed</div>
        <div class="alert error">{html.escape(str(upscale.get("error", "Upscale failed.")))}</div>
        {render_log("Upscale Command", command_text)}
        {render_log("Upscale Output", stdout)}
        {render_log("Upscale Errors", stderr)}
      </div>"""


def render_log(title: str, text: str) -> str:
    if not text:
        return ""
    return f"""
      <div class="mt-4">
        <div class="text-xs font-semibold tracking-widest text-[#626b73] dark:text-[#a7b1ad] mb-1.5">{html.escape(title)}</div>
        <pre class="max-h-64 overflow-auto rounded-2xl border border-[#d9dedb] dark:border-[#33413d] bg-[#f7f7f4] dark:bg-[#111514] p-4 text-xs font-mono leading-relaxed text-[#1e2428] dark:text-[#c3c9c6]">{html.escape(text)}</pre>
      </div>"""


def render_history_modal() -> str:
    return f'''<div id="history-modal" class="modal" aria-hidden="true">
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="history-title">
      <div class="modal-header">
        <h2 id="history-title">Prompt History</h2>
        <button id="history-close" class="secondary icon-button" type="button" aria-label="Close prompt history" title="Close prompt history">{svg_icon("close")}</button>
      </div>
      <div id="history-list" class="history-list">
        <p class="empty-history">No prompts saved yet.</p>
      </div>
    </section>
  </div>'''


def render_templates_modal() -> str:
    return '''<div id="templates-modal" class="modal" aria-hidden="true">
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="templates-title">
      <div class="modal-header">
        <h2 id="templates-title">Prompt Templates</h2>
        <button id="templates-close" class="secondary icon-button" type="button" aria-label="Close templates" title="Close templates">''' + svg_icon("close") + '''</button>
      </div>
      <div style="padding: 8px 18px; border-bottom:1px solid var(--line);">
        <input id="templates-search" type="text" placeholder="Search name or prompt..." style="width:100%;">
      </div>
      <div style="padding: 12px 18px; display:flex; gap:8px; align-items:center; border-bottom:1px solid var(--line);">
        <button id="save-template-btn" class="secondary" type="button">Save Current as Template</button>
        <span style="font-size:12px; color:var(--muted);">Saves prompt + main settings</span>
      </div>
      <div id="templates-list" class="history-list" style="max-height: 380px;">
        <p class="empty-history">No templates saved yet.</p>
      </div>
    </section>
  </div>'''


def render_outputs_modal() -> str:
    return f'''<div id="outputs-modal" class="modal" aria-hidden="true">
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="outputs-title">
      <div class="modal-header">
        <h2 id="outputs-title">Output Images</h2>
        <button id="outputs-close" class="secondary icon-button" type="button" aria-label="Close output images" title="Close output images">{svg_icon("close")}</button>
      </div>

      <div class="p-4 border-b border-[#d9dedb] dark:border-[#33413d] bg-[#f7f7f4]/60 dark:bg-[#111514]/60 space-y-3">
        <input id="gallery-search" type="text" placeholder="Search filename or prefix..." aria-label="Search images"
               class="w-full rounded-2xl border border-[#d9dedb] dark:border-[#33413d] bg-white dark:bg-[#1a201f] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#0f766e]">
        <div class="flex flex-wrap gap-1.5" id="gallery-filters">
          <button type="button" class="gallery-filter active" data-filter="all">All</button>
          <button type="button" class="gallery-filter" data-filter="flux">Flux</button>
          <button type="button" class="gallery-filter" data-filter="zimage">Z-Image</button>
          <button type="button" class="gallery-filter" data-filter="qwen">Qwen</button>
          <button type="button" class="gallery-filter" data-filter="upscaled">Upscaled</button>
        </div>
        <div id="gallery-stats" class="text-xs text-[#626b73] dark:text-[#a7b1ad]"></div>
      </div>

      <div id="outputs-list" class="image-list p-4">
        <p class="empty-history">No images found.</p>
      </div>

      <div class="gallery-actions-bar border-t border-[#d9dedb] dark:border-[#33413d] bg-[#f7f7f4]/60 dark:bg-[#111514]/60 p-4 flex gap-3">
        <button id="gallery-refresh" type="button" class="flex-1 h-11 rounded-2xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-white dark:hover:bg-[#1a201f] text-sm font-semibold">Refresh</button>
        <button id="gallery-bulk-delete" type="button" class="flex-1 h-11 rounded-2xl border border-red-200 dark:border-red-900/60 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 text-sm font-semibold disabled:opacity-40" disabled>Delete Selected</button>
        <button id="gallery-compare" type="button" class="flex-1 h-11 rounded-2xl border border-[#d9dedb] dark:border-[#33413d] hover:bg-white dark:hover:bg-[#1a201f] text-sm font-semibold disabled:opacity-40" disabled>Compare</button>
      </div>
    </section>
  </div>'''


def render_settings_modal() -> str:
    return f'''<div id="settings-modal" class="modal" aria-hidden="true">
    <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="settings-title">
      <div class="modal-header">
        <h2 id="settings-title">Settings</h2>
        <button id="settings-close" class="secondary icon-button" type="button" aria-label="Close settings" title="Close settings">{svg_icon("close")}</button>
      </div>
      <div style="padding: 16px 18px; display: grid; gap: 18px;">
        <div>
          <label style="display:block; margin-bottom:6px; font-weight:650; color:var(--muted);">Theme</label>
          <div style="display:flex; gap:8px;">
            <button type="button" class="secondary theme-btn" data-theme="light">Light</button>
            <button type="button" class="secondary theme-btn" data-theme="dark">Dark</button>
            <button type="button" class="secondary theme-btn" data-theme="system">System</button>
          </div>
        </div>

        <div>
          <label for="default-model" style="display:block; margin-bottom:6px; font-weight:650; color:var(--muted);">Default Model</label>
          <select id="default-model" style="width:100%;"></select>
        </div>

        <label class="checkbox" style="margin:0;">
          <input id="auto-open-gallery" type="checkbox" value="1">
          Auto-open gallery after successful generation
        </label>

        <div style="font-size:12px; color:var(--muted); border-top:1px solid var(--line); padding-top:12px;">
          Keyboard shortcuts<br>
          <strong>Ctrl/Cmd + Enter</strong> — Generate<br>
          <strong>g</strong> — Focus prompt<br>
          <strong>/</strong> — Open gallery<br>
          <strong>h</strong> — Prompt history<br>
          <strong>Esc</strong> — Close modals
        </div>
      </div>
      <div style="padding:12px 18px; border-top:1px solid var(--line); display:flex; justify-content:flex-end; gap:8px;">
        <button id="settings-save" type="button">Save &amp; Close</button>
      </div>
    </section>
  </div>'''


def render_compare_modal() -> str:
    return f'''<div id="compare-modal" class="modal" aria-hidden="true">
    <section class="modal-panel compare-panel" role="dialog" aria-modal="true" aria-labelledby="compare-title">
      <div class="modal-header">
        <h2 id="compare-title">Comparison</h2>
        <button id="compare-close" class="secondary icon-button" type="button" aria-label="Close comparison" title="Close comparison">{svg_icon("close")}</button>
      </div>

      <div class="compare-body">
        <div id="compare-slider-container" class="compare-slider-container">
          <img id="compare-image-a" class="compare-image" alt="Original">
          <div id="compare-image-b-wrapper" class="compare-image-b-wrapper">
            <img id="compare-image-b" class="compare-image" alt="Upscaled / Compared">
          </div>
          <div id="compare-handle" class="compare-handle">
            <div class="compare-handle-line"></div>
            <div class="compare-handle-knob"></div>
          </div>
        </div>

        <div class="compare-labels">
          <div id="compare-label-a">Original</div>
          <div id="compare-label-b">Upscaled</div>
        </div>
      </div>

      <div class="compare-footer">
        <button id="compare-swap" type="button" class="secondary">Swap Sides</button>
        <button id="compare-reset" type="button" class="secondary">Reset Slider</button>
      </div>
    </section>
  </div>'''


@app.get("/")
async def index() -> Response:
    # Build real context so the renewed form + all buttons + model pulldown work.
    # We reuse the same logic the old page() used (this will be cleaned up when we
    # fully delete the giant string builder).
    saved_dimensions = load_form_state()
    values = {
        "model": "zimage",
        "prompt": "A puffin standing on a cliff",
        "width": saved_dimensions["width"],
        "height": saved_dimensions["height"],
        "steps": MODELS["zimage"]["default_steps"],
        "seed": 42,
        "random_seed": False,
        "filename_prefix": default_filename_prefix("zimage"),
        "filename": "",
        "upscale_enabled": False,
        "upscale_resolution": 1024,
        "upscale_resolution_raw": "",
    }

    client_defaults = {
        name: {
            "steps": config["default_steps"],
            "filenamePrefix": config["filename_prefix"],
        }
        for name, config in MODELS.items()
    }
    client_defaults_json = json.dumps(client_defaults)

    js_version = get_static_version("app.js")
    css_version = get_static_version("app.css")

    model_options = "\n".join(
        f'<option value="{html.escape(name)}" {"selected" if values["model"] == name else ""}>{html.escape(config["label"])}</option>'
        for name, config in MODELS.items()
    )

    # Empty on initial GET
    error_html = ""
    result_html = render_result(None, values)

    config_script = f'''<script>
    window.APP_CONFIG = {{
      modelDefaults: {client_defaults_json},
      icons: {{
        check: `{svg_icon("check")}`,
        external: `{svg_icon("external")}`,
        rename: `{svg_icon("rename")}`,
        trash: `{svg_icon("trash")}`,
        upscale: `{svg_icon("upscale")}`,
      }}
    }};
  </script>'''

    # Pre-render modals the same way the legacy code did (keeps them working)
    history_modal = render_history_modal()
    templates_modal = render_templates_modal()
    outputs_modal = render_outputs_modal()
    settings_modal = render_settings_modal()
    compare_modal = render_compare_modal()

    # For initial server-rendered state of the advanced section + theme (reduces flash)
    ui_settings = load_ui_settings()
    show_advanced_by_default = bool(ui_settings.get("show_advanced_by_default"))
    initial_theme = ui_settings.get("theme", "system")   # light | dark | system

    return await render_template(
        "index.html",
        show_renewed_form=True,
        values=values,
        model_options=model_options,
        error_html=error_html,
        result_html=result_html,
        config_script=config_script,
        css_version=css_version,
        js_version=js_version,
        history_modal=history_modal,
        templates_modal=templates_modal,
        outputs_modal=outputs_modal,
        settings_modal=settings_modal,
        compare_modal=compare_modal,
        show_advanced_by_default=show_advanced_by_default,
        initial_theme=initial_theme,
    )


@app.post("/generate")
async def generate():
    form_data = await request.form
    form = {key: form_data.get(key, "").strip() for key in form_data}
    values, errors = validate_form(form)
    if errors:
        return jsonify({"errors": errors}), 400

    await asyncio.to_thread(save_form_dimensions, int(values["width"]), int(values["height"]))
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


@app.post("/form-state/dimensions")
async def form_state_dimensions():
    form_data = await request.form
    try:
        width = validate_dimension(form_data.get("width", ""), "Width")
        height = validate_dimension(form_data.get("height", ""), "Height")
        state = await asyncio.to_thread(save_form_dimensions, width, height)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(state)


@app.get("/settings")
async def get_settings():
    settings = await asyncio.to_thread(load_ui_settings)
    return jsonify(settings)


@app.post("/settings")
async def save_settings():
    form_data = await request.form
    incoming = {k: form_data.get(k) for k in form_data}
    # Coerce some booleans
    for key in ("auto_open_gallery_on_success", "show_advanced_by_default"):
        if key in incoming:
            incoming[key] = incoming[key] in ("1", "true", "on", "yes")

    saved = await asyncio.to_thread(save_ui_settings, incoming)
    return jsonify(saved)


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


@app.get("/prompt-templates")
async def prompt_templates():
    templates = await asyncio.to_thread(load_prompt_templates)
    return jsonify({"templates": templates})


@app.post("/prompt-templates")
async def prompt_templates_save():
    form_data = await request.form
    template = {
        "name": form_data.get("name", "").strip(),
        "prompt": form_data.get("prompt", ""),
        "model": form_data.get("model", ""),
        "width": int(form_data.get("width") or 512),
        "height": int(form_data.get("height") or 512),
        "steps": int(form_data.get("steps") or 9),
        "seed": int(form_data.get("seed") or 42),
        "random_seed": form_data.get("random_seed") == "1",
        "guidance": form_data.get("guidance") or None,
        "lora_scale": form_data.get("lora_scale") or None,
        "negative_prompt": form_data.get("negative_prompt", ""),
        "upscale_enabled": form_data.get("upscale_enabled") == "1",
        "upscale_resolution": int(form_data.get("upscale_resolution") or 1024),
        "filename_prefix": form_data.get("filename_prefix", ""),
    }
    templates = await asyncio.to_thread(add_prompt_template, template)
    return jsonify({"templates": templates})


@app.post("/prompt-templates/delete")
async def prompt_templates_delete():
    form_data = await request.form
    templates = await asyncio.to_thread(delete_prompt_template, form_data.get("name", ""))
    return jsonify({"templates": templates})


@app.post("/prompt-templates/rename")
async def prompt_templates_rename():
    form_data = await request.form
    old_name = form_data.get("old_name", "")
    new_name = form_data.get("new_name", "")
    templates = await asyncio.to_thread(rename_prompt_template, old_name, new_name)
    return jsonify({"templates": templates})


@app.post("/jobs/<job_id>/cancel")
async def cancel_job_endpoint(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    cancelled = await cancel_job(job)
    return jsonify({"cancelled": cancelled, "status": job.get("status")})


@app.get("/output-images")
async def output_images():
    images = await asyncio.to_thread(list_output_images)
    return jsonify({"images": images})


@app.post("/output-images/delete")
async def output_images_delete():
    form_data = await request.form
    filename = form_data.get("filename", "")
    try:
        images = await asyncio.to_thread(delete_output_image, filename)
    except FileNotFoundError as exc:
        images = await asyncio.to_thread(list_output_images)
        return jsonify({"error": str(exc), "images": images}), 404
    except ValueError as exc:
        images = await asyncio.to_thread(list_output_images)
        return jsonify({"error": str(exc), "images": images}), 400
    return jsonify({"images": images})


@app.post("/output-images/upscale")
async def output_images_upscale():
    """Trigger a standalone upscale of an existing output image (from gallery)."""
    form_data = await request.form
    filename = form_data.get("filename", "").strip()
    resolution_raw = form_data.get("resolution", "").strip()

    if not filename:
        return jsonify({"error": "filename is required"}), 400

    try:
        src_path = safe_output_image_path(filename)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not src_path.exists():
        return jsonify({"error": "Image not found"}), 404

    # Determine target resolution (reuse the same default logic as the form)
    try:
        if resolution_raw:
            resolution = parse_int(resolution_raw, "Resolution", 64, 8192)
        else:
            # Default: 2x the short side (same as UI default_upscale_resolution)
            stat = src_path.stat()
            # We don't have width/height, so fall back to a reasonable default or read via PIL if available.
            # For simplicity, use 1024 as a common nice target if we can't infer.
            resolution = 1024
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Create a job so we can stream progress exactly like generation
    job_id = uuid.uuid4().hex
    job: dict[str, object] = {
        "id": job_id,
        "status": "queued",
        "values": {"type": "standalone-upscale", "source": filename},
        "messages": [],
        "queue": asyncio.Queue(),
    }
    JOBS[job_id] = job
    await set_job_status(job, "queued", "queued", "Queued...")

    # Fire the upscale in the background
    asyncio.create_task(run_upscale_only(job_id, src_path, resolution))

    return jsonify({"job_id": job_id})


@app.get("/outputs/<path:filename>")
async def output_file(filename: str):
    try:
        path = safe_output_image_path(filename)
    except ValueError:
        abort(404)

    if not path.exists() or not path.is_file():
        abort(404)

    return await send_file(path)


def main() -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    app.run(host=HOST, port=PORT)


if __name__ == "__main__":
    main()
