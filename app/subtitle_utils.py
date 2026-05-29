import math
import re


def split_text_naturally(text: str, max_parts: int) -> list[str]:
    words = text.split()

    if len(words) <= 8:
        return [text]

    # Intentar cortar por puntuación natural primero
    sentences = re.split(r"(?<=[.!?;:])\s+", text)

    if 1 < len(sentences) <= max_parts:
        return sentences

    # Si no hay puntuación suficiente, cortar en partes equilibradas
    parts_count = min(max_parts, max(1, math.ceil(len(text) / 115)))

    if parts_count <= 1:
        return [text]

    chunk_size = math.ceil(len(words) / parts_count)

    chunks = [
        " ".join(words[i:i + chunk_size])
        for i in range(0, len(words), chunk_size)
    ]

    # Evitar micro-subtítulos
    if len(chunks) > 1 and len(chunks[-1]) < 30:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()

    return chunks


def split_long_segments(
    segments,
    max_chars=115,
    max_duration=7.5,
    min_chars=35,
    max_parts=3,
):
    new_segments = []

    for segment in segments:
        text = segment["text"].strip()
        start = segment["start"]
        end = segment["end"]

        duration = end - start

        if len(text) <= max_chars and duration <= max_duration:
            new_segments.append(segment)
            continue

        # Si no está tan largo, no lo cortes por nervio
        if len(text) < min_chars and duration <= max_duration + 2:
            new_segments.append(segment)
            continue

        estimated_parts_by_chars = math.ceil(len(text) / max_chars)
        estimated_parts_by_duration = math.ceil(duration / max_duration)

        parts_count = min(
            max_parts,
            max(2, estimated_parts_by_chars, estimated_parts_by_duration),
        )

        chunks = split_text_naturally(text, parts_count)

        chunk_duration = duration / len(chunks)

        for i, chunk in enumerate(chunks):
            new_segments.append(
                {
                    "start": start + i * chunk_duration,
                    "end": start + (i + 1) * chunk_duration,
                    "text": chunk.strip(),
                }
            )

    return new_segments