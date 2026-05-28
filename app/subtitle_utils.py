import math


def split_long_segments(segments, max_chars=84, max_duration=6):
    new_segments = []

    for segment in segments:
        text = segment["text"].strip()
        start = segment["start"]
        end = segment["end"]

        duration = end - start

        if len(text) <= max_chars and duration <= max_duration:
            new_segments.append(segment)
            continue

        words = text.split()

        chunk_size = max(1, math.ceil(len(words) / 2))
        chunks = [
            " ".join(words[i:i + chunk_size])
            for i in range(0, len(words), chunk_size)
        ]

        chunk_duration = duration / len(chunks)

        for i, chunk in enumerate(chunks):
            new_segments.append({
                "start": start + i * chunk_duration,
                "end": start + (i + 1) * chunk_duration,
                "text": chunk
            })

    return new_segments