"""Atlassian Document Format (ADF) ⇄ Markdown (7.2).

Jira Cloud's REST API v3 holds rich text (descriptions, comments) as ADF, a JSON tree. Agents
read and write Markdown, so the client converts at its edge and nothing above it sees ADF.

Both directions handle text only: no HTML is produced or parsed, and media become a marker.
Reading covers what Jira's editor writes; an unknown node gives its text. Writing covers the
subset an agent's comment needs (paragraphs, headings, lists, code blocks, inline code, bold,
italic and links); anything else is sent as the text it is."""

import re
from typing import Any, cast

type _Node = dict[str, Any]

MAX_DEPTH = 32
"""Nodes deeper than this give their text with no structure, so a hostile tree cannot recurse
without end."""

_SAFE_LINK = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)


# --- ADF → Markdown -------------------------------------------------------------------------


def to_markdown(doc: object) -> str:
    """The Markdown text of an ADF document (or of any node). `None` or a non-ADF value is the
    empty string; a plain string (Jira's v2 shape) is returned as it is."""
    if isinstance(doc, str):
        return doc.strip()
    if not isinstance(doc, dict):
        return ""
    return _block(cast(_Node, doc), 0).strip()


def _children(node: _Node) -> list[_Node]:
    content = node.get("content")
    if not isinstance(content, list):
        return []
    return [cast(_Node, c) for c in cast(list[Any], content) if isinstance(c, dict)]


def _attrs(node: _Node) -> dict[str, Any]:
    attrs = node.get("attrs")
    return cast(dict[str, Any], attrs) if isinstance(attrs, dict) else {}


def _plain(node: _Node) -> str:
    """Every text under `node`, with no structure. Iterative, so any depth is safe."""
    out: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.get("type") == "text":
            out.append(str(current.get("text", "")))
        elif current.get("type") == "hardBreak":
            out.append("\n")
        elif (inline := _inline_atom(current)) is not None:
            out.append(inline)
        else:
            stack.extend(reversed(_children(current)))
    return "".join(out)


def _blocks(nodes: list[_Node], depth: int, sep: str = "\n\n") -> str:
    return sep.join(text for node in nodes if (text := _block(node, depth)))


def _block(node: _Node, depth: int) -> str:
    if depth > MAX_DEPTH:
        return _plain(node)
    kind = node.get("type")
    children = _children(node)
    match kind:
        case "doc":
            return _blocks(children, depth + 1)
        case "paragraph":
            return _inlines(children, depth + 1)
        case "heading":
            level = _attrs(node).get("level")
            hashes = "#" * (level if isinstance(level, int) and 1 <= level <= 6 else 1)
            return f"{hashes} {_inlines(children, depth + 1)}"
        case "bulletList" | "orderedList":
            return _list(node, depth)
        case "codeBlock":
            language = _attrs(node).get("language")
            lang = language if isinstance(language, str) and language.isalnum() else ""
            return f"```{lang}\n{_plain(node)}\n```"
        case "blockquote" | "panel":
            inner = _blocks(children, depth + 1)
            return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        case "rule":
            return "---"
        case "table":
            return _table(node, depth)
        case "mediaSingle" | "mediaGroup" | "media":
            return "[attachment]"
        case "expand" | "nestedExpand":
            title = _attrs(node).get("title")
            body = _blocks(children, depth + 1)
            return f"**{title}**\n\n{body}" if isinstance(title, str) and title else body
        case "listItem" | "tableCell" | "tableHeader":
            return _blocks(children, depth + 1)
        case _:
            if children and all(_is_inline(child) for child in children):
                return _inlines(children, depth + 1)
            if children:
                return _blocks(children, depth + 1)
            return _plain(node)


def _is_inline(node: _Node) -> bool:
    return (
        node.get("type") == "text"
        or node.get("type") == "hardBreak"
        or (_inline_atom(node) is not None)
    )


def _inline_atom(node: _Node) -> str | None:
    """The text of an inline node that is not a text run, or `None` for anything else."""
    attrs = _attrs(node)
    match node.get("type"):
        case "mention":
            text = attrs.get("text")
            return str(text) if isinstance(text, str) and text else "@someone"
        case "emoji":
            text = attrs.get("text") or attrs.get("shortName")
            return str(text) if isinstance(text, str) else ""
        case "inlineCard" | "blockCard" | "embedCard":
            url = attrs.get("url")
            return f"<{url}>" if isinstance(url, str) and _SAFE_LINK.match(url) else "[link]"
        case "status":
            text = attrs.get("text")
            return f"[{text}]" if isinstance(text, str) else ""
        case "date":
            stamp = attrs.get("timestamp")
            return str(stamp) if stamp is not None else ""
        case "mediaInline":
            return "[attachment]"
        case _:
            return None


def _inlines(nodes: list[_Node], depth: int) -> str:
    out: list[str] = []
    for node in nodes:
        if node.get("type") == "text":
            out.append(_text(node))
        elif node.get("type") == "hardBreak":
            out.append("\n")
        elif (atom := _inline_atom(node)) is not None:
            out.append(atom)
        else:
            out.append(_plain(node))
    return "".join(out)


def _text(node: _Node) -> str:
    text = str(node.get("text", ""))
    if not text:
        return ""
    marks = node.get("marks")
    kinds: dict[str, dict[str, Any]] = {}
    if isinstance(marks, list):
        for mark in cast(list[Any], marks):
            if isinstance(mark, dict):
                m = cast(_Node, mark)
                kinds[str(m.get("type"))] = _attrs(m)
    if "code" in kinds:
        text = f"`{text}`"
    else:
        if "strong" in kinds:
            text = f"**{text}**"
        if "em" in kinds:
            text = f"_{text}_"
        if "strike" in kinds:
            text = f"~~{text}~~"
    href = kinds.get("link", {}).get("href")
    if isinstance(href, str) and _SAFE_LINK.match(href):
        text = f"[{text}]({href})"
    return text


def _list(node: _Node, depth: int) -> str:
    ordered = node.get("type") == "orderedList"
    start = _attrs(node).get("order")
    number = start if isinstance(start, int) and start > 0 else 1
    lines: list[str] = []
    for item in _children(node):
        marker = f"{number}." if ordered else "-"
        number += 1
        body = _block(item, depth + 1) if item.get("type") == "listItem" else _plain(item)
        first, *rest = body.split("\n") if body else [""]
        lines.append(f"{marker} {first}")
        pad = " " * (len(marker) + 1)
        lines.extend(f"{pad}{line}" if line else "" for line in rest)
    return "\n".join(lines)


def _table(node: _Node, depth: int) -> str:
    rows: list[list[str]] = []
    for row in _children(node):
        cells = [
            _block(cell, depth + 1).replace("\n", " ").replace("|", "\\|")
            for cell in _children(row)
        ]
        rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(lines)


# --- Markdown → ADF -------------------------------------------------------------------------

_FENCE = re.compile(r"^```\s*([A-Za-z0-9_+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s{0,3}(\d{1,9})[.)]\s+(.*)$")
_INLINE = re.compile(
    r"`(?P<code>[^`\n]+)`"
    r"|\[(?P<label>[^\]\n]+)\]\((?P<href>(?:https?://|mailto:)[^\s)]+)\)"
    r"|\*\*(?P<strong>[^\n]+?)\*\*"
    r"|(?<![\w*])\*(?P<em1>[^\s*](?:[^*\n]*?[^\s*])?)\*(?![\w*])"
    r"|(?<![\w_])_(?P<em2>[^\s_](?:[^_\n]*?[^\s_])?)_(?![\w_])"
)


def from_markdown(text: str) -> _Node:
    """An ADF document for Markdown `text` (the write subset; see the module's docstring)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[_Node] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            blocks.append({"type": "paragraph", "content": _inline_nodes("\n".join(paragraph))})
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush()
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence, or the end
            code: _Node = {"type": "codeBlock", "content": []}
            if fence.group(1):
                code["attrs"] = {"language": fence.group(1)}
            if "\n".join(body):
                code["content"] = [{"type": "text", "text": "\n".join(body)}]
            blocks.append(code)
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(
                {
                    "type": "heading",
                    "attrs": {"level": len(heading.group(1))},
                    "content": _inline_nodes(heading.group(2).strip()),
                }
            )
            i += 1
            continue
        if _BULLET.match(line) or _ORDERED.match(line):
            flush()
            ordered = _ORDERED.match(line) is not None
            pattern = _ORDERED if ordered else _BULLET
            items: list[_Node] = []
            first = _ORDERED.match(line)
            while i < len(lines) and (match := pattern.match(lines[i])):
                item_text = match.group(match.lastindex or 1)
                items.append(
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": _inline_nodes(item_text)}],
                    }
                )
                i += 1
            lst: _Node = {"type": "orderedList" if ordered else "bulletList", "content": items}
            if ordered and first is not None and int(first.group(1)) != 1:
                lst["attrs"] = {"order": int(first.group(1))}
            blocks.append(lst)
            continue
        if not line.strip():
            flush()
        else:
            paragraph.append(line)
        i += 1
    flush()
    return {"type": "doc", "version": 1, "content": blocks}


def _inline_nodes(text: str, marks: tuple[_Node, ...] = ()) -> list[_Node]:
    """Text nodes for one paragraph's Markdown, with single newlines as hard breaks."""
    nodes: list[_Node] = []
    for n, line in enumerate(text.split("\n")):
        if n:
            nodes.append({"type": "hardBreak"})
        nodes.extend(_marked(line, marks))
    return nodes


def _marked(text: str, marks: tuple[_Node, ...]) -> list[_Node]:
    nodes: list[_Node] = []
    at = 0
    for match in _INLINE.finditer(text):
        if match.start() > at:
            nodes.append(_text_node(text[at : match.start()], marks))
        if match.group("code") is not None:
            # ADF combines `code` only with `link`.
            links = tuple(mark for mark in marks if mark.get("type") == "link")
            nodes.append(_text_node(match.group("code"), (*links, {"type": "code"})))
        elif match.group("label") is not None:
            link: _Node = {"type": "link", "attrs": {"href": match.group("href")}}
            nodes.extend(_marked(match.group("label"), (*marks, link)))
        elif match.group("strong") is not None:
            nodes.extend(_marked(match.group("strong"), (*marks, {"type": "strong"})))
        else:
            inner = match.group("em1") or match.group("em2") or ""
            nodes.extend(_marked(inner, (*marks, {"type": "em"})))
        at = match.end()
    if at < len(text):
        nodes.append(_text_node(text[at:], marks))
    return [node for node in nodes if node.get("text")]


def _text_node(text: str, marks: tuple[_Node, ...]) -> _Node:
    node: _Node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node
