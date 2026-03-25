from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import hashlib
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

from bookverse.models import ChapterSpan, ChunkRecord, ParsedBook


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+", re.UNICODE)
CHAPTER_RE = re.compile(
    r"(?im)^(?:\s*)(?:(?:глава|chapter|часть|part)\s+([^\n]{1,120})|([IVXLCDM]+|\d+))\s*$"
)
HEADING_ONLY_RE = re.compile(
    r"(?is)^(?:\s*)(?:глава|chapter|часть|part)(?:\s+(?:глава|chapter|часть|part))?\s+[^\n]{1,120}\s*$"
)
STOPWORDS = {
    "и", "в", "во", "на", "по", "под", "над", "для", "из", "от", "до", "за", "о", "об",
    "что", "как", "кто", "где", "когда", "ли", "же", "бы", "а", "но", "не", "ни", "это",
    "этот", "эта", "эти", "тот", "та", "те", "у", "с", "со", "к", "ко", "мы", "вы",
    "он", "она", "они", "его", "ее", "её", "их", "или", "про", "из-за", "так", "уже",
}
RAW_SYNONYM_GROUPS = [
    {"автомобиль", "машина", "авто", "транспорт"},
    {"герой", "персонаж", "действующий"},
    {"битва", "бой", "сражение"},
    {"дом", "жилище", "домик"},
    {"любовь", "чувство", "влюбленность"},
    {"семья", "родные", "близкие"},
]
SYNONYM_MAP: dict[str, list[str]] = {}
CHAPTER_QUERY_RE = re.compile(
    r"(?i)(?:глава|главе|главы|главу|chapter)\s*(?:№\s*)?([IVXLCDM]+|\d+)|([IVXLCDM]+|\d+)\s*(?:глава|главе|главы|главу)"
)


def strip_extension(filename: str) -> str:
    return Path(filename).stem.strip() or filename


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8", "cp1251", "koi8-r"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sanitize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def local_tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_section_heading(title: str) -> str:
    cleaned = sanitize_text(title)
    if not cleaned:
        return cleaned
    if re.match(r"(?i)^(?:глава|chapter|часть|part)\b", cleaned):
        return cleaned
    return f"Глава {cleaned}"


def is_heading_only_chunk(text: str) -> bool:
    cleaned = sanitize_text(text)
    if not cleaned:
        return True
    if not HEADING_ONLY_RE.fullmatch(cleaned):
        return False
    meaningful = [token for token in tokenize(cleaned) if normalize_token(token) not in {"глав", "chapter", "част"}]
    return len(meaningful) <= 2


def extract_text_from_fb2(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return re.sub(r"<[^>]+>", " ", xml_text)

    ns_match = re.match(r"\{(.+)\}", root.tag)
    ns = {"fb": ns_match.group(1)} if ns_match else {}
    body_path = ".//fb:body" if ns else ".//body"
    section_path = ".//fb:section" if ns else ".//section"
    title_path = "fb:title" if ns else "title"
    paragraph_path = ".//fb:p" if ns else ".//p"

    pieces: list[str] = []
    for body in root.findall(body_path, ns):
        sections = body.findall(section_path, ns)
        if not sections:
            text = " ".join(part.strip() for part in body.itertext() if part.strip())
            if text:
                pieces.append(text)
            continue
        for section in sections:
            title_node = section.find(title_path, ns)
            title = " ".join(part.strip() for part in title_node.itertext() if part.strip()) if title_node is not None else ""
            if title:
                pieces.append(normalize_section_heading(title))
            paragraphs: list[str] = []
            for child in list(section):
                child_name = local_tag_name(child.tag)
                if child_name in {"title", "section"}:
                    continue
                nodes = [child] if child_name == "p" else child.findall(paragraph_path, ns)
                for paragraph in nodes:
                    text = " ".join(part.strip() for part in paragraph.itertext() if part.strip())
                    if text:
                        paragraphs.append(text)
            if title and paragraphs:
                normalized_title = sanitize_text(title).lower().replace("ё", "е")
                first_paragraph = sanitize_text(paragraphs[0]).lower().replace("ё", "е")
                if first_paragraph == normalized_title or first_paragraph == normalize_section_heading(title).lower().replace("ё", "е"):
                    paragraphs = paragraphs[1:]
            if paragraphs:
                pieces.append("\n\n".join(paragraphs))
    return "\n\n".join(pieces)


def roman_to_int(raw: str) -> int | None:
    raw = raw.strip().lower()
    if not raw:
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    prev = 0
    for char in reversed(raw):
        current = values.get(char)
        if current is None:
            return None
        if current < prev:
            total -= current
        else:
            total += current
            prev = current
    return total or None


def parse_chapter_number(raw: str | None, fallback: int) -> int:
    if not raw:
        return fallback
    cleaned = raw.strip().lower().replace("ё", "е")
    if cleaned.isdigit():
        return int(cleaned)
    roman = roman_to_int(cleaned)
    if roman:
        return roman
    stem_map = {
        "перв": 1,
        "втор": 2,
        "трет": 3,
        "четвер": 4,
        "пят": 5,
        "шест": 6,
        "седьм": 7,
        "восьм": 8,
        "девят": 9,
        "десят": 10,
    }
    for stem, number in stem_map.items():
        if cleaned.startswith(stem):
            return number
    return fallback


def detect_chapters(text: str) -> list[ChapterSpan]:
    matches = list(CHAPTER_RE.finditer(text))
    if not matches:
        return [ChapterSpan(number=1, title="Книга", start=0, end=len(text))]

    chapters: list[ChapterSpan] = []
    for index, match in enumerate(matches):
        raw_number = match.group(1) or match.group(2)
        number = parse_chapter_number(raw_number, index + 1)
        title = match.group(0).strip() or f"Глава {number}"
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(ChapterSpan(number=number, title=title, start=start, end=end))
    return chapters


def build_line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def line_for_offset(line_offsets: list[int], offset: int) -> int:
    return max(1, bisect_right(line_offsets, max(0, offset)) )


def trim_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return start, end


def paragraph_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    segment = text[start:end]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in re.finditer(r"\n\s*\n+", segment):
        raw = trim_span(text, start + cursor, start + match.start())
        if raw:
            spans.append(raw)
        cursor = match.end()
    raw = trim_span(text, start + cursor, end)
    if raw:
        spans.append(raw)
    return spans


def sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    segment = text[start:end]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in re.finditer(r"(?<=[.!?])\s+", segment):
        raw = trim_span(text, start + cursor, start + match.start())
        if raw:
            spans.append(raw)
        cursor = match.end()
    raw = trim_span(text, start + cursor, end)
    if raw:
        spans.append(raw)
    return spans


def normalize_token(token: str) -> str:
    value = token.lower().replace("ё", "е")
    suffixes = (
        "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ее", "ие", "ые", "ое",
        "ий", "ый", "ой", "ам", "ям", "ах", "ях", "ую", "юю", "ая", "яя", "ов", "ев",
        "ом", "ем", "им", "ых", "их", "а", "я", "ы", "и", "е", "о", "у", "ю",
    )
    for suffix in suffixes:
        if value.endswith(suffix) and len(value) - len(suffix) >= 3:
            return value[: -len(suffix)]
    return value


for group in RAW_SYNONYM_GROUPS:
    normalized_group = {normalize_token(item) for item in group}
    for token in normalized_group:
        SYNONYM_MAP[token] = sorted(normalized_group - {token})


def tokenize(text: str) -> list[str]:
    return [match.group(0) for match in TOKEN_RE.finditer(text)]


def expand_token(token: str) -> list[str]:
    normalized = normalize_token(token)
    if not normalized or normalized in STOPWORDS:
        return []
    expanded = [normalized]
    expanded.extend(SYNONYM_MAP.get(normalized, []))
    return expanded


def build_search_text(text: str) -> str:
    bag: list[str] = []
    for token in tokenize(text):
        bag.extend(expand_token(token))
    return " ".join(bag)


def split_large_span(text: str, start: int, end: int, max_chars: int, overlap_chars: int) -> list[tuple[int, int]]:
    spans = sentence_spans(text, start, end)
    if not spans:
        spans = [(start, end)]
    windows: list[tuple[int, int]] = []
    buffer: list[tuple[int, int]] = []
    current_size = 0
    for span in spans:
        span_size = span[1] - span[0]
        if span_size > max_chars:
            cursor = span[0]
            while cursor < span[1]:
                chunk_end = min(span[1], cursor + max_chars)
                windows.append((cursor, chunk_end))
                if chunk_end >= span[1]:
                    break
                cursor = max(cursor + 1, chunk_end - overlap_chars)
            continue
        if buffer and current_size + span_size > max_chars:
            windows.append((buffer[0][0], buffer[-1][1]))
            overlap: list[tuple[int, int]] = []
            overlap_size = 0
            for item in reversed(buffer):
                overlap.insert(0, item)
                overlap_size += item[1] - item[0]
                if overlap_size >= overlap_chars:
                    break
            buffer = overlap[:]
            current_size = sum(item[1] - item[0] for item in buffer)
        buffer.append(span)
        current_size += span_size
    if buffer:
        windows.append((buffer[0][0], buffer[-1][1]))
    return windows


def build_chunks(
    book_id: str,
    text: str,
    chapters: list[ChapterSpan],
    max_chars: int,
    overlap_chars: int,
) -> list[ChunkRecord]:
    line_offsets = build_line_offsets(text)
    chunks: list[ChunkRecord] = []
    chunk_order = 0

    for chapter in chapters:
        units = paragraph_spans(text, chapter.start, chapter.end)
        normalized_units: list[tuple[int, int]] = []
        for unit_start, unit_end in units:
            if unit_end - unit_start > max_chars:
                normalized_units.extend(split_large_span(text, unit_start, unit_end, max_chars, overlap_chars))
            else:
                normalized_units.append((unit_start, unit_end))
        if not normalized_units:
            normalized_units = [(chapter.start, chapter.end)]

        buffer: list[tuple[int, int]] = []
        current_size = 0
        for unit_start, unit_end in normalized_units:
            unit_size = unit_end - unit_start
            if buffer and current_size + unit_size > max_chars:
                chunk_start = buffer[0][0]
                chunk_end = buffer[-1][1]
                chunk_text = text[chunk_start:chunk_end].strip()
                if is_heading_only_chunk(chunk_text):
                    buffer = []
                    current_size = 0
                    continue
                chunks.append(
                    ChunkRecord(
                        id=f"chk_{uuid.uuid4().hex}",
                        book_id=book_id,
                        chunk_order=chunk_order,
                        chapter_number=chapter.number,
                        chapter_title=chapter.title,
                        line_start=line_for_offset(line_offsets, chunk_start),
                        line_end=line_for_offset(line_offsets, max(chunk_end - 1, chunk_start)),
                        char_start=chunk_start,
                        char_end=chunk_end,
                        text=chunk_text,
                        search_text=build_search_text(chunk_text),
                    )
                )
                chunk_order += 1
                overlap: list[tuple[int, int]] = []
                overlap_size = 0
                for item in reversed(buffer):
                    overlap.insert(0, item)
                    overlap_size += item[1] - item[0]
                    if overlap_size >= overlap_chars:
                        break
                buffer = overlap[:]
                current_size = sum(item[1] - item[0] for item in buffer)
            buffer.append((unit_start, unit_end))
            current_size += unit_size

        if buffer:
            chunk_start = buffer[0][0]
            chunk_end = buffer[-1][1]
            chunk_text = text[chunk_start:chunk_end].strip()
            if is_heading_only_chunk(chunk_text):
                continue
            chunks.append(
                ChunkRecord(
                    id=f"chk_{uuid.uuid4().hex}",
                    book_id=book_id,
                    chunk_order=chunk_order,
                    chapter_number=chapter.number,
                    chapter_title=chapter.title,
                    line_start=line_for_offset(line_offsets, chunk_start),
                    line_end=line_for_offset(line_offsets, max(chunk_end - 1, chunk_start)),
                    char_start=chunk_start,
                    char_end=chunk_end,
                    text=chunk_text,
                    search_text=build_search_text(chunk_text),
                )
            )
            chunk_order += 1
    return chunks


def parse_book_content(
    book_id: str,
    filename: str,
    raw_bytes: bytes,
    file_type: str,
    max_chunk_chars: int,
    overlap_chars: int,
) -> ParsedBook:
    decoded = decode_text(raw_bytes)
    if file_type.lower() == "fb2":
        decoded = extract_text_from_fb2(decoded)
    content = sanitize_text(decoded)
    if not content:
        raise ValueError("Файл пустой или не содержит читаемого текста")
    chapters = detect_chapters(content)
    chunks = build_chunks(book_id, content, chapters, max_chars=max_chunk_chars, overlap_chars=overlap_chars)
    if not chunks:
        raise ValueError("Не удалось разбить книгу на фрагменты")
    return ParsedBook(
        title=strip_extension(filename),
        file_type=file_type.upper(),
        content=content,
        chapters=chapters,
        chunks=chunks,
    )


def extract_requested_chapter(query: str) -> int | None:
    for match in CHAPTER_QUERY_RE.finditer(query):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        parsed = parse_chapter_number(raw, 0)
        if parsed > 0:
            return parsed
    return None


def query_terms(query: str) -> list[str]:
    bag: list[str] = []
    for token in tokenize(query):
        bag.extend(expand_token(token))
    return bag


def hashing_vector(text: str, dim: int) -> list[float]:
    counter: Counter[int] = Counter()
    normalized = " ".join(query_terms(text)) or sanitize_text(text.lower())
    sequence = normalized if normalized else text.lower()
    for size in (3, 4, 5):
        for index in range(len(sequence) - size + 1):
            ngram = sequence[index:index + size]
            digest = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "little") % dim
            counter[bucket] += 1
    vector = [0.0] * dim
    norm = 0.0
    for bucket, value in counter.items():
        weight = float(value)
        vector[bucket] = weight
        norm += weight * weight
    if norm == 0.0:
        return vector
    norm = norm ** 0.5
    return [value / norm for value in vector]
