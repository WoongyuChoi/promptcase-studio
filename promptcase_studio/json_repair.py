from __future__ import annotations


def escape_json_string_control_characters(text: str) -> tuple[str, bool]:
    """Escape literal control characters only when they occur inside JSON strings.

    Some compatible AI endpoints intermittently return a quoted JSON value with
    a real newline or tab instead of ``\n`` or ``\t``.  Repairing only those
    characters preserves the JSON structure and does not guess missing fields or
    alter semantic validation.
    """

    replacements = {
        "\b": "b",
        "\t": "t",
        "\n": "n",
        "\f": "f",
        "\r": "r",
    }
    output: list[str] = []
    in_string = False
    escaped = False
    changed = False

    for character in text:
        if not in_string:
            output.append(character)
            if character == '"':
                in_string = True
            continue

        if escaped:
            if ord(character) < 0x20:
                output.append(replacements.get(character, f"u{ord(character):04x}"))
                changed = True
            else:
                output.append(character)
            escaped = False
            continue

        if character == "\\":
            output.append(character)
            escaped = True
        elif character == '"':
            output.append(character)
            in_string = False
        elif ord(character) < 0x20:
            escaped_character = replacements.get(
                character,
                f"u{ord(character):04x}",
            )
            output.extend(("\\", escaped_character))
            changed = True
        else:
            output.append(character)

    return "".join(output), changed
