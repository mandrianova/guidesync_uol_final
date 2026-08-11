from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen

from guidesync_agent.app_logging import configure_logging
from guidesync_agent.settings import get_settings

MODEL_ARCHIVE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-en-v0_19.tar.bz2"
)
MODEL_ARCHIVE_SHA256 = "912804855a04745fa77a30be545b3f9a5d15c4d66db00b88cbcd4921df605ac7"
MODEL_MARKER_NAME = ".guidesync-model-sha256"

logger = logging.getLogger(__name__)


def download_model(model_dir: Path) -> None:
    marker = model_dir / MODEL_MARKER_NAME
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == MODEL_ARCHIVE_SHA256:
        logger.info("Kokoro model cache is already verified at %s", model_dir)
        return
    parent = model_dir.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    if model_dir.resolve().parent != parent or model_dir.name != "kokoro-en-v0_19":
        raise ValueError("Refusing to replace an unexpected TTS model path.")
    with TemporaryDirectory(prefix="guidesync-kokoro-", dir=parent) as temp_dir:
        temp_path = Path(temp_dir)
        archive_path = temp_path / "kokoro-en-v0_19.tar.bz2"
        logger.info("Downloading Kokoro model archive from %s", MODEL_ARCHIVE_URL)
        digest = hashlib.sha256()
        with urlopen(MODEL_ARCHIVE_URL, timeout=60) as response, archive_path.open("wb") as out:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != MODEL_ARCHIVE_SHA256:
            raise ValueError("Downloaded Kokoro model archive checksum did not match.")
        extract_dir = temp_path / "extract"
        extract_dir.mkdir()
        with tarfile.open(archive_path, "r:bz2") as archive:
            archive.extractall(extract_dir, filter="data")
        extracted_model = extract_dir / "kokoro-en-v0_19"
        if not (extracted_model / "model.onnx").is_file():
            raise ValueError("Kokoro model archive did not contain the expected model.")
        if model_dir.exists():
            shutil.rmtree(model_dir)
        shutil.copytree(extracted_model, model_dir)
        marker.write_text(MODEL_ARCHIVE_SHA256 + "\n", encoding="utf-8")
    logger.info("Kokoro model cache installed and verified at %s", model_dir)


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Download the pinned Kokoro TTS model.")
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    download_model(args.model_dir or get_settings().video_presentation.model_dir)


if __name__ == "__main__":
    main()
