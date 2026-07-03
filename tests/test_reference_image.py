import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

import app as image_app


def valid_form(model: str = "flux2-9B-face") -> dict[str, str]:
    return {
        "model": model,
        "prompt": "portrait reference test",
        "width": "512",
        "height": "512",
        "steps": "4",
        "seed": "42",
        "filename_prefix": "flux",
    }


class ReferenceImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.reference_dir = self.root / "reference_images"
        self.state_path = self.root / "reference_state.json"
        self.default_face = self.root / "face.png"
        self.default_face.write_bytes(b"fake-png")

        self.patches = [
            patch.object(image_app, "REFERENCE_IMAGES_DIR", self.reference_dir, create=True),
            patch.object(image_app, "REFERENCE_STATE_PATH", self.state_path, create=True),
            patch.object(image_app, "DEFAULT_REFERENCE_IMAGE_PATH", self.default_face, create=True),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_face_model_uses_default_reference_when_no_state_exists(self) -> None:
        values, errors = image_app.validate_form(valid_form())

        self.assertEqual([], errors)
        self.assertEqual(str(self.default_face.resolve()), values["reference_image"]["path"])
        self.assertEqual("face.png", values["reference_image"]["display_name"])

    def test_face_model_requires_existing_reference_image(self) -> None:
        self.default_face.unlink()

        values, errors = image_app.validate_form(valid_form())

        self.assertEqual("flux2-9B-face", values["model"])
        self.assertIn("Choose a valid reference image for Flux face generation.", errors)

    def test_non_face_models_do_not_require_reference_image(self) -> None:
        self.default_face.unlink()

        values, errors = image_app.validate_form(valid_form("zimage"))

        self.assertEqual([], errors)
        self.assertNotIn("reference_image", values)

    def test_local_path_endpoint_persists_active_reference(self) -> None:
        reference = self.root / "custom.webp"
        reference.write_bytes(b"fake-webp")

        async def run_request():
            client = image_app.app.test_client()
            return await client.post("/reference-image/path", form={"path": str(reference)})

        response = asyncio.run(run_request())
        data = asyncio.run(response.get_json())

        self.assertEqual(200, response.status_code)
        self.assertEqual(str(reference.resolve()), data["reference"]["path"])
        self.assertEqual(str(reference.resolve()), image_app.load_active_reference_image()["path"])

    def test_upload_endpoint_saves_managed_reference_file(self) -> None:
        async def run_request():
            client = image_app.app.test_client()
            file_storage = FileStorage(
                stream=io.BytesIO(b"fake-png"),
                filename="portrait.png",
                content_type="image/png",
            )
            return await client.post("/reference-image/upload", files={"file": file_storage})

        response = asyncio.run(run_request())
        data = asyncio.run(response.get_json())
        saved_path = Path(data["reference"]["path"])

        self.assertEqual(200, response.status_code)
        self.assertEqual(self.reference_dir.resolve(), saved_path.parent)
        self.assertTrue(saved_path.exists())
        self.assertEqual(str(saved_path), image_app.load_active_reference_image()["path"])

    def test_generation_command_includes_selected_reference_path(self) -> None:
        reference = self.root / "selected.png"
        reference.write_bytes(b"fake-png")
        image_app.save_active_reference_image(reference, "selected.png")
        values, errors = image_app.validate_form(valid_form())
        self.assertEqual([], errors)

        command_path = self.root / "mflux-generate-flux2-edit"
        command_path.write_text("#!/bin/sh\n", encoding="utf-8")
        command_path.chmod(0o755)
        model_copy = dict(image_app.MODELS["flux2-9B-face"])
        model_copy["command"] = command_path

        async def fake_run_command(command, phase, job):
            return 0, [], []

        async def run_generation():
            with patch.dict(image_app.MODELS, {"flux2-9B-face": model_copy}):
                with patch.object(image_app, "run_command", fake_run_command):
                    return await image_app.run_generation(values, {"messages": [], "queue": asyncio.Queue()})

        result = asyncio.run(run_generation())

        self.assertIn("--image-paths", result["command"])
        image_arg_index = result["command"].index("--image-paths") + 1
        self.assertEqual(str(reference.resolve()), result["command"][image_arg_index])
