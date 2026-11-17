from typing import Any

from agentic_jira import from_markdown, to_markdown


def text(value: str, *marks: dict[str, Any]) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def doc(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "doc", "version": 1, "content": list(content)}


def para(*content: dict[str, Any]) -> dict[str, Any]:
    return {"type": "paragraph", "content": list(content)}


def test_a_description_reads_as_markdown() -> None:
    adf = doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Acceptance criteria")]},
        para(
            text("Clients over "),
            text("100", {"type": "strong"}),
            text(" requests get "),
            text("429", {"type": "code"}),
            text(", see "),
            text("the docs", {"type": "link", "attrs": {"href": "https://example.test/rl"}}),
            text("."),
        ),
        {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [para(text("per key"))]},
                {"type": "listItem", "content": [para(text("per IP"))]},
            ],
        },
        {"type": "codeBlock", "attrs": {"language": "python"}, "content": [text("x = 1")]},
        para(
            {"type": "mention", "attrs": {"id": "a1", "text": "@Ada"}},
            {"type": "hardBreak"},
            text("thanks"),
        ),
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "m1"}}]},
    )

    assert to_markdown(adf) == (
        "## Acceptance criteria\n\n"
        "Clients over **100** requests get `429`, see [the docs](https://example.test/rl).\n\n"
        "- per key\n- per IP\n\n"
        "```python\nx = 1\n```\n\n"
        "@Ada\nthanks\n\n"
        "[attachment]"
    )


def test_ordered_lists_tables_and_quotes() -> None:
    adf = doc(
        {
            "type": "orderedList",
            "attrs": {"order": 3},
            "content": [{"type": "listItem", "content": [para(text("third"))]}],
        },
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableHeader", "content": [para(text("Key"))]},
                        {"type": "tableHeader", "content": [para(text("Value"))]},
                    ],
                },
                {
                    "type": "tableRow",
                    "content": [
                        {"type": "tableCell", "content": [para(text("a|b"))]},
                        {"type": "tableCell", "content": [para(text("1"))]},
                    ],
                },
            ],
        },
        {"type": "blockquote", "content": [para(text("quoted"))]},
    )

    assert to_markdown(adf) == "3. third\n\n| Key | Value |\n|---|---|\n| a\\|b | 1 |\n\n> quoted"


def test_unsafe_links_and_html_stay_text() -> None:
    adf = doc(
        para(
            text("click", {"type": "link", "attrs": {"href": "javascript:alert(1)"}}),
            text(" <script>alert(1)</script>"),
        )
    )

    assert to_markdown(adf) == "click <script>alert(1)</script>"


def test_unknown_nodes_give_their_text_and_odd_values_are_empty() -> None:
    adf = doc({"type": "someFutureBlock", "content": [para(text("still here"))]})

    assert to_markdown(adf) == "still here"
    assert to_markdown(None) == ""
    assert to_markdown(42) == ""
    assert to_markdown("  plain v2 text ") == "plain v2 text"


def test_a_deep_tree_does_not_recurse_without_end() -> None:
    node: dict[str, Any] = para(text("bottom"))
    for _ in range(500):
        node = {"type": "blockquote", "content": [node]}

    assert "bottom" in to_markdown(doc(node))


def test_a_comment_is_written_as_adf() -> None:
    adf = from_markdown(
        "## Summary\n\n"
        "The limit is **per key**, see [docs](https://example.test) and `RATE`.\n"
        "Second line.\n\n"
        "- one\n- _two_\n\n"
        "2. b\n3. c\n\n"
        "```python\nx = 1\n```"
    )

    assert adf == {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Summary")]},
            para(
                text("The limit is "),
                text("per key", {"type": "strong"}),
                text(", see "),
                text("docs", {"type": "link", "attrs": {"href": "https://example.test"}}),
                text(" and "),
                text("RATE", {"type": "code"}),
                text("."),
                {"type": "hardBreak"},
                text("Second line."),
            ),
            {
                "type": "bulletList",
                "content": [
                    {"type": "listItem", "content": [para(text("one"))]},
                    {"type": "listItem", "content": [para(text("two", {"type": "em"}))]},
                ],
            },
            {
                "type": "orderedList",
                "attrs": {"order": 2},
                "content": [
                    {"type": "listItem", "content": [para(text("b"))]},
                    {"type": "listItem", "content": [para(text("c"))]},
                ],
            },
            {"type": "codeBlock", "attrs": {"language": "python"}, "content": [text("x = 1")]},
        ],
    }


def test_written_html_and_unsafe_links_are_plain_text() -> None:
    adf = from_markdown("<b>hi</b> [x](javascript:alert(1)) snake_case_name")

    assert adf["content"] == [para(text("<b>hi</b> [x](javascript:alert(1)) snake_case_name"))]


def test_code_inside_bold_keeps_only_the_code_mark() -> None:
    adf = from_markdown("**see `x`**")

    assert adf["content"] == [para(text("see ", {"type": "strong"}), text("x", {"type": "code"}))]


def test_markdown_round_trips() -> None:
    source = "# Title\n\nSome **bold** and `code`.\n\n- a\n- b\n\n```\nraw\n```"

    assert to_markdown(from_markdown(source)) == source
