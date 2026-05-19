from pathlib import Path
import subprocess
import re
from faster_whisper import WhisperModel


FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"


def extract_audio(video_path: Path, audio_path: Path) -> None:
    """
    Extrae el audio del video y lo convierte a WAV mono 16 kHz.
    """
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path)
    ]
    subprocess.run(cmd, check=True)


def get_audio_duration(audio_path: Path) -> float:
    """
    Devuelve la duración del audio en segundos usando ffprobe.
    """
    cmd = [
        FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def extract_audio_chunk(
    audio_path: Path,
    chunk_path: Path,
    start_sec: float,
    duration_sec: float
) -> None:
    """
    Extrae un fragmento WAV del audio principal.
    """
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(audio_path),
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(chunk_path)
    ]
    subprocess.run(cmd, check=True)


def sec_to_srt_time(seconds: float) -> str:
    """
    Convierte segundos float a formato SRT: HH:MM:SS,mmm
    """
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3_600_000
    total_ms %= 3_600_000
    minutes = total_ms // 60_000
    total_ms %= 60_000
    secs = total_ms // 1000
    ms = total_ms % 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def normalize_text(text: str) -> str:
    """
    Limpia espacios y normaliza el texto.
    """
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def looks_like_english(text: str) -> bool:
    """
    Detector básico para frases obviamente en inglés.
    Sirve para filtrar delirios grotescos cuando el idioma elegido no es inglés.
    """
    lower = text.lower()
    english_markers = [
        " the ", " and ", " you ", " i ", " don't ", " thanks ",
        " please ", " come on ", " very good ", " let's ", " goodbye "
    ]
    padded = f" {lower} "
    hits = sum(marker in padded for marker in english_markers)
    return hits >= 2


def is_repetitive_text(text: str) -> bool:
    """
    Detecta repeticiones raras.
    """
    words = text.lower().split()
    if len(words) < 6:
        return False

    unique_ratio = len(set(words)) / len(words)
    if unique_ratio < 0.45:
        return True

    if len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            return True

    return False


def is_bad_segment(text: str, duration: float, language: str) -> bool:
    """
    Filtra segmentos claramente malos o delirantes.
    """
    t = normalize_text(text)
    lower = t.lower()

    if not t:
        return True

    banned_exact = {
        "the end",
        "music",
        "[music]",
        "(music)",
    }
    if lower in banned_exact:
        return True

    if duration > 8 and len(t) < 15:
        return True

    if is_repetitive_text(t):
        return True

    # Si el idioma esperado NO es inglés, filtramos inglés obvio inventado.
    if language != "en" and looks_like_english(t):
        return True

    return False


def get_profile_settings(audio_profile: str) -> dict:
    """
    Define parámetros según el tipo de audio que el usuario elija.
    """
    profiles = {
        "clean": {
            "chunk_duration": 60,
            "min_silence_duration_ms": 500,
            "no_speech_threshold": 0.6,
        },
        "music_effects": {
            "chunk_duration": 45,
            "min_silence_duration_ms": 700,
            "no_speech_threshold": 0.6,
        },
        "old_film": {
            "chunk_duration": 45,
            "min_silence_duration_ms": 700,
            "no_speech_threshold": 0.6,
        },
    }

    return profiles.get(audio_profile, profiles["old_film"])


def transcribe_chunk(
    model: WhisperModel,
    chunk_path: Path,
    offset_sec: float,
    language: str,
    audio_profile: str
):
    """
    Transcribe un chunk y devuelve segmentos con tiempos absolutos.
    """
    settings = get_profile_settings(audio_profile)

    transcribe_kwargs = {
        "task": "transcribe",
        "beam_size": 1,
        "best_of": 1,
        "temperature": 0.0,
        "vad_filter": False,
        "vad_parameters": dict(
            min_silence_duration_ms=settings["min_silence_duration_ms"]
        ),
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "compression_ratio_threshold": 2.0,
        "log_prob_threshold": -1.0,
        "no_speech_threshold": settings["no_speech_threshold"],
    }

    # Si el usuario elige detectar automáticamente, no forzamos idioma.
    if language != "auto":
        transcribe_kwargs["language"] = language

    segments, info = model.transcribe(str(chunk_path), **transcribe_kwargs)

    results = []
    for seg in segments:
        text = normalize_text(seg.text)
        start = seg.start + offset_sec
        end = seg.end + offset_sec
        duration = end - start

        if is_bad_segment(text, duration, language):
            continue

        results.append({
            "start": start,
            "end": end,
            "text": text
        })

    return results


def merge_close_segments(segments, max_gap=0.35, max_chars=84):
    """
    Une segmentos cercanos para evitar subtítulos ridículamente cortos.
    """
    if not segments:
        return []

    merged = [segments[0]]

    for seg in segments[1:]:
        prev = merged[-1]
        gap = seg["start"] - prev["end"]
        combined_text = f'{prev["text"]} {seg["text"]}'

        if gap <= max_gap and len(combined_text) <= max_chars:
            prev["end"] = seg["end"]
            prev["text"] = combined_text
        else:
            merged.append(seg)

    return merged


def write_srt(segments, srt_path: Path) -> None:
    """
    Escribe el archivo SRT final con formato estándar.
    """
    with srt_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start = sec_to_srt_time(seg["start"])
            end = sec_to_srt_time(seg["end"])
            text = seg["text"].strip()

            f.write(f"{i}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n")
            f.write("\n")


def generate_srt(
    video_path: Path,
    output_dir: Path,
    language: str = "es",
    audio_profile: str = "old_film"
) -> Path:
    """
    Función principal que genera un SRT desde un video.
    Esta es la función que usará la app web.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    audio_path = output_dir / "audio.wav"
    srt_path = output_dir / "output.srt"

    print("1) Extrayendo audio del video...")
    extract_audio(video_path, audio_path)

    print("2) Midiendo duración del audio...")
    total_duration = get_audio_duration(audio_path)
    print(f"Duración total: {total_duration:.2f} segundos")

    print("3) Cargando modelo de transcripción...")
    model = WhisperModel("large-v3", device="cpu", compute_type="int8")

    settings = get_profile_settings(audio_profile)
    chunk_duration = settings["chunk_duration"]

    all_segments = []
    chunk_index = 0
    start_sec = 0.0

    print("4) Procesando por chunks...")
    while start_sec < total_duration:
        current_duration = min(chunk_duration, total_duration - start_sec)
        chunk_path = chunks_dir / f"chunk_{chunk_index:04d}.wav"

        print(
            f"   - Chunk {chunk_index + 1}: "
            f"{start_sec:.2f}s a {start_sec + current_duration:.2f}s"
        )

        extract_audio_chunk(audio_path, chunk_path, start_sec, current_duration)

        chunk_segments = transcribe_chunk(
            model=model,
            chunk_path=chunk_path,
            offset_sec=start_sec,
            language=language,
            audio_profile=audio_profile
        )

        all_segments.extend(chunk_segments)

        start_sec += chunk_duration
        chunk_index += 1

    print("5) Uniendo segmentos cercanos...")
    final_segments = merge_close_segments(all_segments)

    print(f"6) Escribiendo SRT en: {srt_path}")
    write_srt(final_segments, srt_path)

    print("Listo. Ya se generó el archivo SRT.")
    return srt_path