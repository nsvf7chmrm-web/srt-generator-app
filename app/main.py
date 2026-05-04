import os
import subprocess
from pathlib import Path
from faster_whisper import WhisperModel

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

FFMPEG = "ffmpeg"


def extract_audio(video_path, audio_path):
    cmd = [
        FFMPEG,
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path)
    ]
    subprocess.run(cmd, check=True)


def split_audio(audio_path, chunk_dir, chunk_length=60):
    chunk_dir.mkdir(exist_ok=True)
    cmd = [
        FFMPEG,
        "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", str(chunk_length),
        "-c", "copy",
        str(chunk_dir / "chunk_%03d.wav")
    ]
    subprocess.run(cmd, check=True)


def transcribe_chunks(chunk_dir, language="es"):
    print("🔥 Cargando modelo GPU...")
    model = WhisperModel(
        "large-v3",
        device="cuda",
        compute_type="float16"
    )

    all_segments = []
    current_time = 0

    chunks = sorted(chunk_dir.glob("*.wav"))

    for i, chunk in enumerate(chunks):
        print(f"🎧 Procesando chunk {i+1}/{len(chunks)}")

        segments, _ = model.transcribe(
            str(chunk),
            language=language,
            vad_filter=True
        )

        for seg in segments:
            seg.start += current_time
            seg.end += current_time
            all_segments.append(seg)

        current_time += 60  # duración chunk

    return all_segments


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(segments, output_file):
    with open(output_file, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_time(seg.start)} --> {format_time(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")


def generate_srt(video_path, language="es"):
    job_id = video_path.stem
    work_dir = OUTPUT_DIR / job_id
    chunk_dir = work_dir / "chunks"

    work_dir.mkdir(exist_ok=True)

    audio_path = work_dir / "audio.wav"

    print("🎬 Extrayendo audio...")
    extract_audio(video_path, audio_path)

    print("✂️ Dividiendo en chunks...")
    split_audio(audio_path, chunk_dir)

    print("🧠 Transcribiendo...")
    segments = transcribe_chunks(chunk_dir, language)

    srt_path = work_dir / "output.srt"

    print("📝 Generando SRT...")
    write_srt(segments, srt_path)

    return srt_path


if __name__ == "__main__":
    video_file = UPLOAD_DIR / "test.mp4"
    generate_srt(video_file)