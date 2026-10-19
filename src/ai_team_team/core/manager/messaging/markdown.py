"""Deterministic titles and bounded previews without model-generated metadata."""

import re

from ai_team_team.core.exceptions import ToolArgumentError


def extract(markdown, config, *, validate_title=True):
    if type(markdown) is not str or not markdown.strip():
        raise ToolArgumentError("A chat message requires nonempty Markdown text.")
    lines = markdown.splitlines(keepends=True)
    fence = None
    title, excluded = "", set()
    previous = None
    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", stripped)
        if fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            previous = None
            continue
        if match:
            fence = match[1]
            previous = None
            continue
        if stripped.startswith(("    ", "\t")):
            previous = None
            continue
        heading = re.match(r"^ {0,3}#(?:[ \t]+(.*?)|[ \t]*)$", stripped)
        if heading:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[1] or "").strip()
            excluded = {index}
            break
        if previous is not None and re.match(r"^ {0,3}=+[ \t]*$", stripped):
            title = lines[previous].strip()
            excluded = {previous, index}
            break
        previous = index if stripped.strip() else None
    if validate_title and len(title) > config.title_max_characters:
        raise ToolArgumentError(f"The message title exceeds {config.title_max_characters} characters; shorten it.")
    preview = "".join(line for index, line in enumerate(lines) if index not in excluded).strip()
    return title, preview[:config.preview_characters]
