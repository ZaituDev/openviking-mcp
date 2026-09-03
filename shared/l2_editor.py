from __future__ import annotations

import re

# Regex for ATX heading line: 0-3 leading spaces, 1 to 6 # characters,
# followed by a space/tab or end-of-line.
_ATX_HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+.*|[ \t]*)?$")

# Regex for fenced code block opening: 0-3 leading spaces, 3 or more ` or ~
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})(.*)$")


def _check_fence_open(line: str) -> tuple[str, int] | None:
    line_stripped = line.rstrip("\r\n")
    m = _FENCE_OPEN_RE.match(line_stripped)
    if not m:
        return None
    fence_run = m.group(1)
    info = m.group(2)
    fence_char = fence_run[0]
    # For backtick code fences, info string cannot contain backticks
    if fence_char == "`" and "`" in info:
        return None
    return fence_char, len(fence_run)


def _check_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    line_stripped = line.rstrip("\r\n")
    escaped = re.escape(fence_char)
    pat = rf"^[ ]{{0,3}}{escaped}{{{fence_len},}}[ \t]*$"
    return bool(re.match(pat, line_stripped))


def _parse_atx_heading_level(line: str) -> int | None:
    line_stripped = line.rstrip("\r\n")
    m = _ATX_HEADING_RE.match(line_stripped)
    if not m:
        return None
    return len(m.group(1))


def apply_section_edit(
    document: str, heading_selector: str, replacement_content: str
) -> str:
    """Apply a section-level edit to an ATX markdown document.

    Replaces the body of the section identified by `heading_selector` with
    `replacement_content`, preserving content outside the section byte-for-byte.
    """
    clean_selector = heading_selector.strip()
    if not clean_selector:
        raise ValueError(f"Section heading not found: {heading_selector!r}")

    # Split document lines preserving line terminators
    lines_info: list[tuple[int, int, str]] = []
    pos = 0
    for line in document.splitlines(keepends=True):
        lines_info.append((pos, pos + len(line), line))
        pos += len(line)

    # First pass: find matching heading outside fenced code blocks
    matches: list[tuple[int, int, int, str, int]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for idx, (start, end, line) in enumerate(lines_info):
        if in_fence:
            if _check_fence_close(line, fence_char, fence_len):
                in_fence = False
                fence_char = ""
                fence_len = 0
            continue
        else:
            open_info = _check_fence_open(line)
            if open_info is not None:
                in_fence = True
                fence_char, fence_len = open_info
                continue

        lvl = _parse_atx_heading_level(line)
        if lvl is not None and line.strip() == clean_selector:
            matches.append((idx, start, end, line, lvl))

    if len(matches) == 0:
        raise ValueError(f"Section heading not found: {clean_selector}")
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous section heading (multiple matches): {clean_selector}"
        )

    match_idx, matched_start, matched_end, matched_line, matched_level = matches[0]

    # Validate replacement content: all headings outside fences must be strictly deeper
    r_in_fence = False
    r_fence_char = ""
    r_fence_len = 0
    for r_line in replacement_content.splitlines(keepends=True):
        if r_in_fence:
            if _check_fence_close(r_line, r_fence_char, r_fence_len):
                r_in_fence = False
                r_fence_char = ""
                r_fence_len = 0
            continue
        else:
            r_open_info = _check_fence_open(r_line)
            if r_open_info is not None:
                r_in_fence = True
                r_fence_char, r_fence_len = r_open_info
                continue

        lvl = _parse_atx_heading_level(r_line)
        if lvl is not None and lvl <= matched_level:
            raise ValueError(
                f"Replacement content contains heading of equal or higher level: {r_line.strip()}"
            )

    # Find section boundary: next heading with level <= matched_level outside fences
    next_heading_start = len(document)
    s_in_fence = False
    s_fence_char = ""
    s_fence_len = 0

    for idx in range(match_idx + 1, len(lines_info)):
        start, end, line = lines_info[idx]
        if s_in_fence:
            if _check_fence_close(line, s_fence_char, s_fence_len):
                s_in_fence = False
                s_fence_char = ""
                s_fence_len = 0
            continue
        else:
            open_info = _check_fence_open(line)
            if open_info is not None:
                s_in_fence = True
                s_fence_char, s_fence_len = open_info
                continue

        lvl = _parse_atx_heading_level(line)
        if lvl is not None and lvl <= matched_level:
            next_heading_start = start
            break

    prefix = document[:matched_start]
    preserved_heading = document[matched_start:matched_end].rstrip("\r\n")
    suffix = document[next_heading_start:]
    body = replacement_content.strip()

    if suffix:
        if body:
            middle = f"\n{body}\n\n"
        else:
            middle = "\n\n"
    else:
        if body:
            middle = f"\n{body}\n"
        else:
            middle = "\n"

    return f"{prefix}{preserved_heading}{middle}{suffix}"
