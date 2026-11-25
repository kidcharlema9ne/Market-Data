"""Render the saved COT System report for mail clients using inline styles."""

from html import escape
from html.parser import HTMLParser
import re


class ReportParser(HTMLParser):
    text_tags = {"h1", "h2", "h3", "p", "li", "th", "td"}

    def __init__(self):
        super().__init__()
        self.blocks = []
        self.in_body = False
        self.tag = None
        self.parts = []
        self.color = None
        self.table = None
        self.row = None

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return
        if tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in self.text_tags:
            self.tag = tag
            self.parts = []
            style = dict(attrs).get("style") or ""
            match = re.search(r"background(?:-color)?:\s*(#[\da-fA-F]{6})\b", style)
            self.color = match[1] if match else None
        elif tag == "br" and self.tag:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.in_body and tag == self.tag:
            value = " ".join("".join(self.parts).split())
            if tag in {"td", "th"} and self.row is not None:
                self.row.append((value, self.color))
            elif value:
                self.blocks.append((tag, value))
            self.tag = None
        elif tag == "tr" and self.table is not None and self.row:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table:
            self.blocks.append(("table", self.table))
            self.table = None
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and self.tag:
            self.parts.append(data)


def format_table(rows):
    headers = [value for value, _ in rows[0]]
    plain, rendered = [], []
    if len(headers) <= 5:
        rendered.append('<table width="100%" style="border-collapse:collapse;font-size:13px">')
        for index, row in enumerate(rows):
            rendered.append("<tr>")
            tag = "th" if index == 0 else "td"
            for value, color in row:
                background = color or ("#e6edf4" if index == 0 else "#ffffff")
                style = f"padding:5px;text-align:left;border-bottom:1px solid #dbe2e8;background-color:{background}"
                rendered.append(f'<{tag} style="{style}">{escape(value)}</{tag}>')
            rendered.append("</tr>")
            plain.append(" | ".join(value for value, _ in row))
        rendered.append("</table>")
        return plain, rendered

    for row in rows[1:]:
        (market, color), *details = row
        details = [(label, value) for label, (value, _) in zip(headers[1:], details) if value]
        fields = []
        for label, value in details:
            fields.append(
                '<span style="display:inline-block;margin:0 14px 5px 0">'
                f"<strong>{escape(label)}</strong> {escape(value)}</span>"
            )
        background = color or "#e6edf4"
        rendered.append(
            '<div style="margin:0 0 10px;border:1px solid #dbe2e8">'
            f'<div style="padding:7px 9px;background-color:{background}"><strong>{escape(market)}</strong></div>'
            f'<div style="padding:7px 9px 2px">{"".join(fields)}</div></div>'
        )
        plain.append(" | ".join([market] + [f"{label} {value}" for label, value in details]))
    return plain, rendered


def format_report(source, intro):
    """Return equivalent plain text and styled HTML for multipart email."""
    parser = ReportParser()
    parser.feed(source)
    parser.close()
    if not parser.blocks or parser.blocks[0][0] != "h1":
        raise ValueError("The saved COT System report has no report heading.")

    plain = [intro, ""]
    rendered = [
        '<html><body><div style="max-width:720px;margin:auto;font:15px/1.4 Arial,sans-serif;color:#172b3b">',
        f'<p style="margin:0 0 12px">{escape(intro)}</p>',
    ]
    for tag, value in parser.blocks:
        if tag == "table":
            lines, markup = format_table(value)
            plain.extend(lines)
            plain.append("")
            rendered.extend(markup)
            continue
        plain.extend((value, ""))
        styles = {
            "h1": "font-size:22px;line-height:1.25;margin:0 0 10px",
            "h2": "font-size:17px;margin:21px 0 8px",
            "h3": "font-size:16px;margin:16px 0 8px",
        }
        style = styles.get(tag, "margin:0 0 8px")
        if value.upper().startswith(("DATE MISMATCH", "WARNING")):
            style += ";padding:8px;background-color:#fff0da;color:#702300;font-weight:bold"
        element = "p" if tag == "li" else tag
        prefix = "• " if tag == "li" else ""
        rendered.append(f'<{element} style="{style}">{prefix}{escape(value)}</{element}>')
    rendered.append("</div></body></html>")
    return "\n".join(plain).rstrip() + "\n", "\n".join(rendered)
