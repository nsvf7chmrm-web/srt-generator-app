from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol

from dotenv import load_dotenv
from openai import OpenAI
from app.subtitle_utils import split_long_segments

load_dotenv()


@dataclass
class SubtitleBlock:
    index: str
    timecode: str
    text_lines: List[str]
    raw_text: str


class Translator(Protocol):
    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        ...


class OpenAITranslator:
    def __init__(self, model: str = "gpt-4.1-mini"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found")

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        numbered_payload = "\n".join(
            f"<<{i}>> {text}"
            for i, text in enumerate(texts, start=1)
        )

        system_prompt = (
            "You are an expert audiovisual subtitle translator. "
            "Translate naturally for film and television subtitles. "
            "Preserve tone, intent, and emotional meaning. "
            "Do not merge entries. "
            "Do not omit entries. "
            "Preserve numbering markers exactly."
        )

        user_prompt = f"""
Source language: {source_lang}
Target language: {target_lang}

Translate these subtitle entries.

Rules:
- Keep <<1>>, <<2>>, etc.
- One output per entry.
- No explanations.

Entries:
{numbered_payload}
""".strip()

        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        return self._parse_numbered_output(
            response.output_text.strip(),
            expected_count=len(texts),
        )

    @staticmethod
    def _parse_numbered_output(
        output_text: str,
        expected_count: int,
    ) -> List[str]:
        pattern = re.compile(
            r"<<(?P<num>\d+)>>\s?(?P<text>.*?)(?=(?:\n<<\d+>>)|\Z)",
            re.DOTALL,
        )

        matches = pattern.findall(output_text)

        if len(matches) != expected_count:
            raise ValueError(
                f"Expected {expected_count} entries but got {len(matches)}"
            )

        translated_entries = []

        for expected_num, (num, text) in enumerate(matches, start=1):
            if int(num) != expected_num:
                raise ValueError(
                    f"Number mismatch. Expected <<{expected_num}>> but got <<{num}>>"
                )

            translated_entries.append(text.strip())

        return translated_entries


TIME_CODE_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}(?:\s+.*)?$"
)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def srt_time_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000
    )


def seconds_to_srt_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))

    hours = total_ms // 3_600_000
    total_ms %= 3_600_000

    minutes = total_ms // 60_000
    total_ms %= 60_000

    secs = total_ms // 1000
    millis = total_ms % 1000

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_timecode(timecode: str) -> tuple[float, float]:
    start_raw, end_raw = timecode.split("-->")
    start = srt_time_to_seconds(start_raw.strip())
    end = srt_time_to_seconds(end_raw.strip().split()[0])
    return start, end


def make_timecode(start: float, end: float) -> str:
    return f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}"


def parse_srt(srt_text: str) -> List[SubtitleBlock]:
    srt_text = normalize_newlines(srt_text).strip()

    if not srt_text:
        return []

    chunks = re.split(r"\n\s*\n", srt_text)
    blocks: List[SubtitleBlock] = []

    for chunk in chunks:
        lines = chunk.split("\n")

        if len(lines) < 2:
            continue

        index = lines[0].strip()
        timecode = lines[1].strip()
        text_lines = lines[2:] if len(lines) > 2 else []
        raw_text = "\n".join(text_lines)

        if not TIME_CODE_RE.match(timecode):
            raise ValueError(f"Invalid SRT timecode block:\n\n{chunk}")

        blocks.append(
            SubtitleBlock(
                index=index,
                timecode=timecode,
                text_lines=text_lines,
                raw_text=raw_text,
            )
        )

    return blocks


def render_segments_as_srt(segments: list[dict]) -> str:
    rendered_blocks = []

    for i, segment in enumerate(segments, start=1):
        timecode = make_timecode(segment["start"], segment["end"])
        text = segment["text"].strip()

        rendered_blocks.append(
            f"{i}\n{timecode}\n{text}"
        )

    return "\n\n".join(rendered_blocks) + "\n"


def chunk_list(
    items: List[SubtitleBlock],
    chunk_size: int,
) -> List[List[SubtitleBlock]]:
    return [
        items[i:i + chunk_size]
        for i in range(0, len(items), chunk_size)
    ]


def translate_batch_with_retries(
    translator: Translator,
    texts: List[str],
    source_lang: str,
    target_lang: str,
    retries: int = 3,
) -> List[str]:
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return translator.translate_batch(
                texts,
                source_lang,
                target_lang,
            )
        except Exception as e:
            last_error = e
            print(f"Retry {attempt}/{retries} failed: {e}")
            time.sleep(1)

    raise last_error


def translate_srt_file(
    input_path: Path,
    source_lang: str,
    target_lang: str,
    output_dir: Path,
    chunk_size: int = 20,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    original_text = input_path.read_text(encoding="utf-8-sig")
    blocks = parse_srt(original_text)

    translator = OpenAITranslator()
    grouped_blocks = chunk_list(blocks, chunk_size)

    all_translated_texts: List[str] = []
    total_batches = len(grouped_blocks)

    for batch_number, batch in enumerate(grouped_blocks, start=1):
        texts = [block.raw_text for block in batch]

        print(f"Processing batch {batch_number}/{total_batches}")

        translated_batch = translate_batch_with_retries(
            translator=translator,
            texts=texts,
            source_lang=source_lang,
            target_lang=target_lang,
            retries=2,
        )

        all_translated_texts.extend(translated_batch)

    segments = []

    for block, translated_text in zip(blocks, all_translated_texts):
        start, end = parse_timecode(block.timecode)

        segments.append(
            {
                "start": start,
                "end": end,
                "text": translated_text,
            }
        )

    segments = split_long_segments(segments)

    output_filename = f"{input_path.stem}.{target_lang.lower()}.srt"
    output_path = output_dir / output_filename

    output_text = render_segments_as_srt(segments)

    output_path.write_text(
        output_text,
        encoding="utf-8",
    )

    return output_path