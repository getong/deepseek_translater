"""Detect and protect source-code samples embedded in Markdown."""

import re


_FENCE_OPEN_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})[^\r\n]*$")
_CODE_START_PATTERNS = (
    re.compile(r"^\s*(?:UCLASS|USTRUCT|UENUM|UINTERFACE)\s*\("),
    re.compile(r"^\s*(?:public\s+)?class\s+[A-Za-z_]\w*(?:_API)?(?:\s+[A-Za-z_]\w*)?\s*:\s*"),
    re.compile(r"^\s*#\s*(?:include|define|pragma|if|ifdef|ifndef)\b"),
    re.compile(r"^\s*[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)+\s*\("),
    re.compile(
        r"^\s*(?:[A-Za-z_]\w*(?:::\w+)*(?:<[^>]+>)?[\s*&]+)+"
        r"[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)+\s*\([^;)]*$"
    ),
    re.compile(
        r"^\s*(?:[A-Za-z_]\w*(?:::\w+)*(?:<[^>]+>)?[\s*&]+)+"
        r"[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)*\s*\([^;]*\)\s*(?::.*)?$"
    ),
)
_CODE_PLACEHOLDER_RE = re.compile(
    r"<!-- DTS_CODE_BLOCK_(?P<number>\d{4}) -->"
)


def _is_existing_fence(line):
    return _FENCE_OPEN_RE.match(line) is not None


def _find_closing_fence(lines, start):
    opening = _FENCE_OPEN_RE.match(lines[start])
    fence = opening.group("fence")
    closing_re = re.compile(
        rf"^[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$"
    )
    for index in range(start + 1, len(lines)):
        if closing_re.match(lines[index]):
            return index + 1
    return len(lines)


def _is_code_start(line):
    return any(pattern.match(line) for pattern in _CODE_START_PATTERNS)


def _brace_delta(line):
    """Count structural braces while ignoring quoted strings and // comments."""
    delta = 0
    quote = None
    escaped = False
    index = 0
    while index < len(line):
        char = line[index]
        next_char = line[index + 1] if index + 1 < len(line) else ""
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "/" and next_char == "/":
            break
        elif char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
        index += 1
    return delta


def _find_code_sample_end(lines, start):
    depth = 0
    saw_opening_brace = False
    for index in range(start, len(lines)):
        delta = _brace_delta(lines[index])
        if delta > 0:
            saw_opening_brace = True
        depth += delta
        if saw_opening_brace and depth <= 0:
            return index + 1
        if not saw_opening_brace and index - start >= 12:
            return None
    return None


def _code_language(first_line):
    if re.match(r"^\s*public\s+class\s+\w+\s*:\s*\w+", first_line):
        return "csharp"
    return "cpp"


def fence_unmarked_code_blocks(content):
    """Wrap brace-delimited C++/C# samples in fenced Markdown blocks."""
    lines = content.splitlines()
    output = []
    converted = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if _is_existing_fence(line):
            end = _find_closing_fence(lines, index)
            output.extend(lines[index:end])
            index = end
            continue

        if _is_code_start(line):
            end = _find_code_sample_end(lines, index)
            if end is not None:
                if output and output[-1] != "":
                    output.append("")
                output.append(f"```{_code_language(line)}")
                output.extend(lines[index:end])
                output.append("```")
                if end < len(lines) and lines[end] != "":
                    output.append("")
                converted += 1
                index = end
                continue

        output.append(line)
        index += 1

    if not converted:
        return content, 0

    trailing_newline = "\n" if content.endswith("\n") else ""
    return "\n".join(output) + trailing_newline, converted


def mask_fenced_code_blocks(content):
    """Replace fenced blocks with stable placeholders and return exact originals."""
    lines = content.splitlines(keepends=True)
    output = []
    blocks = []
    index = 0

    while index < len(lines):
        line_without_ending = lines[index].rstrip("\r\n")
        if not _is_existing_fence(line_without_ending):
            output.append(lines[index])
            index += 1
            continue

        plain_lines = [item.rstrip("\r\n") for item in lines]
        end = _find_closing_fence(plain_lines, index)
        block = "".join(lines[index:end])
        placeholder = f"<!-- DTS_CODE_BLOCK_{len(blocks) + 1:04d} -->"
        if placeholder in content:
            raise ValueError(f"reserved code placeholder already exists: {placeholder}")
        line_ending = "\n" if block.endswith(("\n", "\r")) else ""
        output.append(placeholder + line_ending)
        blocks.append(block)
        index = end

    return "".join(output), blocks


def partition_fenced_code_blocks(content):
    """Split Markdown into prose and exact fenced-code segments."""
    lines = content.splitlines(keepends=True)
    segments = []
    prose_lines = []
    index = 0

    while index < len(lines):
        line_without_ending = lines[index].rstrip("\r\n")
        if not _is_existing_fence(line_without_ending):
            prose_lines.append(lines[index])
            index += 1
            continue

        if prose_lines:
            segments.append((False, "".join(prose_lines)))
            prose_lines = []

        plain_lines = [item.rstrip("\r\n") for item in lines]
        end = _find_closing_fence(plain_lines, index)
        segments.append((True, "".join(lines[index:end])))
        index = end

    if prose_lines:
        segments.append((False, "".join(prose_lines)))

    return segments


def remove_model_added_code_fences(content):
    """Unwrap fences added by the model while source code was masked."""
    lines = content.splitlines(keepends=True)
    output = []
    removed = 0
    index = 0

    while index < len(lines):
        opening_line = lines[index].rstrip("\r\n")
        if not _is_existing_fence(opening_line):
            output.append(lines[index])
            index += 1
            continue

        plain_lines = [item.rstrip("\r\n") for item in lines]
        end = _find_closing_fence(plain_lines, index)
        has_closing_fence = end <= len(lines) and end > index + 1
        if has_closing_fence:
            closing_line = plain_lines[end - 1]
            has_closing_fence = bool(
                re.match(r"^[ \t]*(`{3,}|~{3,})[ \t]*$", closing_line)
            )
        if not has_closing_fence:
            output.append(lines[index])
            index += 1
            continue

        output.extend(lines[index + 1:end - 1])
        removed += 1
        index = end

    return "".join(output), removed


def restore_fenced_code_blocks(content, blocks):
    """Restore exact code blocks and discard model-added code fences."""
    found = _CODE_PLACEHOLDER_RE.findall(content)
    expected = [f"{index:04d}" for index in range(1, len(blocks) + 1)]
    if found != expected:
        raise ValueError(
            f"code placeholders changed (expected {expected}, found {found})"
        )

    restored, removed_fences = remove_model_added_code_fences(content)
    for index, block in enumerate(blocks, 1):
        placeholder = f"<!-- DTS_CODE_BLOCK_{index:04d} -->"
        restored = restored.replace(placeholder, block.rstrip("\r\n"), 1)
    return restored, removed_fences


def _code_block_signature(block):
    """Return stable leading code lines used to align an existing cache."""
    lines = block.splitlines()
    if len(lines) >= 2 and _is_existing_fence(lines[0]):
        lines = lines[1:]
    if lines and re.match(r"^[ \t]*(`{3,}|~{3,})[ \t]*$", lines[-1]):
        lines = lines[:-1]

    significant = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        significant.append(re.sub(r"\s+", " ", stripped))
        if len(significant) == 2:
            break
    return tuple(significant)


def restore_source_code_in_translation(source, translated):
    """Replace translated code samples with the corresponding source blocks."""
    source, _ = fence_unmarked_code_blocks(source)
    translated, converted = fence_unmarked_code_blocks(translated)
    _, source_blocks = mask_fenced_code_blocks(source)
    masked_translation, translated_blocks = mask_fenced_code_blocks(translated)

    if len(source_blocks) != len(translated_blocks):
        return translated, False, (
            "code block count changed "
            f"({len(source_blocks)} -> {len(translated_blocks)})"
        )

    for index, (source_block, translated_block) in enumerate(
        zip(source_blocks, translated_blocks), 1
    ):
        source_signature = _code_block_signature(source_block)
        translated_signature = _code_block_signature(translated_block)
        if source_signature != translated_signature:
            return translated, False, (
                f"code block {index} does not match the source sample"
            )

    repaired, _ = restore_fenced_code_blocks(masked_translation, source_blocks)
    changed = repaired != translated or converted > 0
    return repaired, changed, None
