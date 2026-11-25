"""Keep the COT System report's tables and colors in email clients."""

from html import escape, unescape
from html.parser import HTMLParser
import re


class EmailReport(HTMLParser):
    styles = {
        "body": "margin:12px;font:13px Arial,sans-serif",
        "h1": "font-size:18px;margin:0 0 4px",
        "h2": "font-size:15px;margin:12px 0 4px",
        "p": "margin:4px 0;color:#333",
        "table": "border-collapse:collapse;font:13px Arial,sans-serif",
        "th": "background-color:#1f3864;color:#fff;font-size:12px;"
              "padding:5px 7px;white-space:nowrap;text-align:right",
        "td": "padding:3px 7px;border:1px solid #ddd;text-align:right;"
              "white-space:nowrap;line-height:1.25",
    }

    def __init__(self, intro):
        super().__init__(convert_charrefs=False)
        self.in_body = False
        self.has_heading = False
        self.column = 0
        self.plain = [intro, "\n\n"]
        self.markup = ["<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                       "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
                       "</head>"]
        self.intro = intro

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
        if not self.in_body:
            return

        style = self.styles.get(tag)
        attributes = dict(attrs)
        if tag == "h1":
            self.has_heading = True
        if tag == "tr":
            self.column = 0
        if tag in {"th", "td"}:
            if self.column < 2:
                alignment = ("left", "center")[self.column]
                style += f";text-align:{alignment}"
            if self.column:
                self.plain.append(" | ")
            self.column += 1
        if tag == "div" and "wrap" in (attributes.get("class") or "").split():
            style = "max-width:100%;overflow-x:auto"
        if style:
            existing = attributes.get("style")
            attributes["style"] = f"{style};{existing}" if existing else style
            markup = "".join(
                f' {name}="{escape(value, quote=True)}"' if value is not None else f" {name}"
                for name, value in attributes.items()
            )
            self.markup.append(f"<{tag}{markup}>")
        else:
            self.markup.append(self.get_starttag_text())
        if tag == "body":
            self.markup.append(f'<p style="margin:0 0 10px">{escape(self.intro)}</p>')
        if tag == "br":
            self.plain.append("\n")

    def handle_endtag(self, tag):
        if not self.in_body:
            return
        self.markup.append(f"</{tag}>")
        if tag in {"h1", "h2", "h3", "p", "li", "tr"}:
            self.plain.append("\n")
        if tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body:
            self.markup.append(data)
            self.plain.append(data)

    def handle_entityref(self, name):
        self.handle_reference(f"&{name};")

    def handle_charref(self, name):
        self.handle_reference(f"&#{name};")

    def handle_reference(self, reference):
        if self.in_body:
            self.markup.append(reference)
            self.plain.append(unescape(reference))


def format_report(source, intro):
    """Return the plain-text fallback and the original tables with inline styles."""
    report = EmailReport(intro)
    report.feed(source)
    report.close()
    if not report.has_heading:
        raise ValueError("The saved COT System report has no report heading.")

    plain = re.sub(r"\n{3,}", "\n\n", "".join(report.plain)).rstrip() + "\n"
    return plain, "".join(report.markup) + "</html>"
