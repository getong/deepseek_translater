"""Shared cleanup helpers for Markdown produced by document converters."""

import re


# Source documents use eight hexadecimal digits. Some existing translations
# shortened the token, so accept six or seven digits only at a token boundary.
_INTERNAL_ANCHOR_TOKEN = (
    r"idx_(?:[0-9a-f]{8}|[0-9a-f]{6,7}(?=[^0-9a-f]|$))"
)
_INTERNAL_ANCHOR_RE = re.compile(_INTERNAL_ANCHOR_TOKEN, re.IGNORECASE)

_HTML_ANCHOR_RE = re.compile(
    rf"<a\b"
    rf"(?=[^>]*(?:id|name|href)\s*=\s*['\"]?#?{_INTERNAL_ANCHOR_TOKEN})"
    rf"[^>]*>(.*?)</a\s*>",
    re.IGNORECASE | re.DOTALL,
)
_MARKDOWN_LINK_RE = re.compile(
    rf"(?<!!)\[([^\]\n]*)\]\(\s*#{_INTERNAL_ANCHOR_TOKEN}\s*\)",
    re.IGNORECASE,
)
_MARKDOWN_SPAN_RE = re.compile(
    rf"\[([^\]\n]*)\][ \t]*\{{[^{{}}\n]*#{_INTERNAL_ANCHOR_TOKEN}[^{{}}\n]*\}}",
    re.IGNORECASE,
)
_MARKDOWN_ATTRIBUTE_RE = re.compile(
    rf"[ \t]*\{{[^{{}}\n]*#{_INTERNAL_ANCHOR_TOKEN}[^{{}}\n]*\}}",
    re.IGNORECASE,
)
_BACKTICKED_ANCHOR_RE = re.compile(
    rf"(?P<before>[ \t]?)`+[ \t]*{_INTERNAL_ANCHOR_TOKEN}[ \t]*`+"
    rf"(?P<after>[ \t]?)",
    re.IGNORECASE,
)
_BARE_ANCHOR_RE = re.compile(
    rf"(?P<before>[ \t]?){_INTERNAL_ANCHOR_TOKEN}(?P<after>[ \t]?)",
    re.IGNORECASE,
)


def _keep_single_separator(match):
    """Keep natural spacing after removing an inline anchor."""
    before = match.group("before")
    after = match.group("after")
    if before and after:
        prefix = match.string[:match.start()].rstrip()
        suffix = match.string[match.end():].lstrip()
        if prefix and suffix and _is_cjk(prefix[-1]) and _is_cjk(suffix[0]):
            return ""
        return " "
    return before or after


def _is_cjk(character):
    return (
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or "\u3040" <= character <= "\u30ff"
        or "\uac00" <= character <= "\ud7af"
    )


def count_internal_anchor_artifacts(content):
    """Count converter-generated ``idx_<hash>`` tokens in content."""
    return len(_INTERNAL_ANCHOR_RE.findall(content))


def contains_internal_anchor_artifacts(content):
    """Return whether content still contains a converter-generated anchor."""
    return _INTERNAL_ANCHOR_RE.search(content) is not None


def remove_internal_anchor_artifacts(content):
    """Remove internal index anchors while preserving their visible text."""
    removed_count = count_internal_anchor_artifacts(content)
    if not removed_count:
        return content, 0

    content = _HTML_ANCHOR_RE.sub(r"\1", content)
    content = _MARKDOWN_LINK_RE.sub(r"\1", content)
    content = _MARKDOWN_SPAN_RE.sub(r"\1", content)
    content = _MARKDOWN_ATTRIBUTE_RE.sub("", content)
    content = _BACKTICKED_ANCHOR_RE.sub(_keep_single_separator, content)
    content = _BARE_ANCHOR_RE.sub(_keep_single_separator, content)
    return content, removed_count
