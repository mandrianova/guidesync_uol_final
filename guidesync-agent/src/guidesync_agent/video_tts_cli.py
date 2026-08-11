from __future__ import annotations

import argparse
import json
import sys
import wave
from array import array
from collections.abc import Iterable
from importlib import import_module
from importlib.metadata import version
from pathlib import Path


def synthesize(request_path: Path, output_dir: Path, result_path: Path) -> None:
    sherpa_onnx = import_module("sherpa_onnx")

    payload = json.loads(request_path.read_text(encoding="utf-8"))
    model_dir = Path(payload["model_dir"])
    config = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(model_dir / "model.onnx"),
                voices=str(model_dir / "voices.bin"),
                tokens=str(model_dir / "tokens.txt"),
                data_dir=str(model_dir / "espeak-ng-data"),
            ),
            provider="cpu",
            debug=False,
            num_threads=int(payload["num_threads"]),
        ),
        max_num_sentences=1,
    )
    if not config.validate():
        raise ValueError("Invalid sherpa-onnx Kokoro configuration.")
    tts = sherpa_onnx.OfflineTts(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    segments = []
    for slide in payload["slides"]:
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = int(payload["voice_id"])
        generation.speed = float(payload["speed"])
        generation.silence_scale = 0.2
        audio = tts.generate(slide["narration"], generation)
        if len(audio.samples) == 0 or audio.sample_rate <= 0:
            raise RuntimeError(f"Kokoro returned empty audio for {slide['slide_id']}.")
        output_path = output_dir / slide["artifact_name"]
        pcm = pcm16_bytes(audio.samples)
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(audio.sample_rate)
            output.writeframes(pcm)
        segments.append({"slide_id": slide["slide_id"], "artifact_name": slide["artifact_name"]})
    result_path.write_text(
        json.dumps(
            {
                "backend_version": version("sherpa-onnx"),
                "model": payload["model_id"],
                "voice": payload["voice"],
                "voice_id": payload["voice_id"],
                "speed": payload["speed"],
                "segments": segments,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def pcm16_bytes(samples: Iterable[float]) -> bytes:
    pcm = array(
        "h",
        (round(max(-1.0, min(1.0, sample)) * 32_767) for sample in samples),
    )
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm.tobytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bounded Kokoro narration segments.")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    synthesize(args.request, args.output_dir, args.result)


if __name__ == "__main__":
    main()
