"""Safe quotation normalization for newly generated document output."""
from __future__ import annotations


_OPEN_TO_CLOSE = {'“': '”', '„': '“', '«': '»', '‹': '›'}
_OPEN_GLYPHS = ('«', '„', '‚')
_CLOSE_GLYPHS = ('»', '“', '‘')
_OPEN_BOUNDARY = set('([{—–:;')
_CLOSE_BOUNDARY = set('.,;:!?)]}')


def normalize_output_quotes(value: object) -> str:
    """Convert balanced quotation pairs to Ukrainian guillemets.

    ASCII pairs are recognized only at clear word boundaries. Nested pairs are
    rendered with Ukrainian inner quotation marks. If any pair is unmatched or
    ambiguous, the original text is returned unchanged; apostrophes are never
    treated as quotation marks.
    """
    text = str(value or '')
    replacements: dict[int, str] = {}
    stack: list[tuple[str, str, int]] = []
    for index, char in enumerate(text):
        if char == '"':
            if index and text[index - 1] == '\\':
                return text
            previous = text[index - 1] if index else ''
            following = text[index + 1] if index + 1 < len(text) else ''
            can_open = (not previous or previous.isspace() or previous in _OPEN_BOUNDARY) and bool(following) and not following.isspace()
            can_close = bool(previous) and not previous.isspace() and (
                not following or following.isspace() or following in _CLOSE_BOUNDARY
            )
            if following == '"' and stack and stack[-1][0] == 'ascii' and previous and not previous.isspace():
                can_close = True
            if can_open and not can_close:
                depth = len(stack)
                if depth >= len(_OPEN_GLYPHS):
                    return text
                stack.append(('ascii', '"', depth))
                replacements[index] = _OPEN_GLYPHS[depth]
            elif can_close and stack and stack[-1][0] == 'ascii':
                _, _, depth = stack.pop()
                replacements[index] = _CLOSE_GLYPHS[depth]
            else:
                return text
            continue

        if char in _OPEN_TO_CLOSE:
            if stack and stack[-1][0] == 'pair' and stack[-1][1] == char:
                _, _, depth = stack.pop()
                replacements[index] = _CLOSE_GLYPHS[depth]
            else:
                depth = len(stack)
                if depth >= len(_OPEN_GLYPHS):
                    return text
                stack.append(('pair', _OPEN_TO_CLOSE[char], depth))
                replacements[index] = _OPEN_GLYPHS[depth]
            continue

        if char in {'”', '“', '»', '›'}:
            if not stack or stack[-1][0] != 'pair' or stack[-1][1] != char:
                return text
            _, _, depth = stack.pop()
            replacements[index] = _CLOSE_GLYPHS[depth]

    if stack:
        return text
    return ''.join(replacements.get(index, char) for index, char in enumerate(text))


def normalize_output_tree(value):
    """Normalize paired quotes recursively in generated metadata values."""
    if isinstance(value, str):
        return normalize_output_quotes(value)
    if isinstance(value, list):
        return [normalize_output_tree(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_output_tree(item) for item in value)
    if isinstance(value, dict):
        return {key: normalize_output_tree(item) for key, item in value.items()}
    return value
