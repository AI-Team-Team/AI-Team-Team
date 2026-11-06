"""Small Markdown readers keep checks focused on declared documentation contracts."""

import ast
import inspect
import re
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "docs/user/API_Reference.md"


def heading_anchors(text):
    """Resolve local ATX heading anchors, including duplicate headings and fences."""
    anchors, fence = set(), None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        heading = re.match(r"^#{1,6} (.+)$", line) if fence is None else None
        if heading is None:
            continue
        plain = "".join(character for character in heading[1].strip().lower()
                        if character in "_- " or unicodedata.category(character)[0] in "LMN")
        plain = re.sub(r"[\ufe00-\ufe0f\U000e0100-\U000e01ef]", "", plain).replace(" ", "-")
        candidate, suffix = plain, 0
        while candidate in anchors:
            suffix += 1
            candidate = f"{plain}-{suffix}"
        anchors.add(candidate)
    return anchors


def section(text, heading):
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n") + len(heading) + 1
    following = re.search(r"^#{1," + str(level) + r"} ", text[start:], re.M)
    return text[start:start + following.start()] if following else text[start:]


def table(text):
    rows = []
    for line in text.splitlines():
        if line.startswith("| "):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                rows.append(cells)
    return rows


def uncode(value):
    return value.strip("`")


def documented_signature(value):
    """Read parameter declarations without evaluating Markdown expressions."""
    declaration = ast.parse("def " + uncode(value) + ":\n    pass\n").body[0]
    args = declaration.args
    if args.posonlyargs or args.vararg or args.kwarg:
        raise ValueError("Documented model-tool signatures must use named ordinary parameters.")
    defaults = [inspect.Parameter.empty] * (len(args.args) - len(args.defaults))
    defaults.extend(ast.literal_eval(item) for item in args.defaults)
    result = [(arg.arg, inspect.Parameter.POSITIONAL_OR_KEYWORD, default)
              for arg, default in zip(args.args, defaults)]
    result.extend((arg.arg, inspect.Parameter.KEYWORD_ONLY,
                   inspect.Parameter.empty if default is None else ast.literal_eval(default))
                  for arg, default in zip(args.kwonlyargs, args.kw_defaults))
    return declaration.name, result


def runnable_blocks(path):
    pattern = r"^<!-- runnable: ([^\n]+) -->\s+```python\n(.*?)\n```"
    return [(name, code + "\n") for name, code in re.findall(
        pattern, path.read_text(encoding="utf-8"), re.S | re.M)]
