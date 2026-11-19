"""XenForo BB-code export for an album. / Экспорт BB-кода XenForo для альбома.

Layout (per the reference post):
1. Title line — yellow bold (template configurable, default ``#FFD34D``);
2. one block per section: bold subheading with the section name, then a
   heading-less ``[spoiler]`` with one media link per line.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_HEADING_TEMPLATE = "[B][SIZE=6][COLOR=#FFD34D]{title}[/COLOR][/SIZE][/B]"


@dataclass
class BBSection:
    """One section of the export. / Одна секция экспорта."""

    name: str
    links: list[str]


def format_media(url: str, media_tag: str = "IMG", custom_media_tag: str = "") -> str:
    """One media link line. / Одна строка медиа-ссылки."""
    tag = (media_tag or "IMG").strip().upper()
    if tag == "CUSTOM":
        tag = (custom_media_tag or "IMG").strip().strip("[]") or "IMG"
    return f"[{tag}]{url}[/{tag}]"


def build_bbcode(title: str, sections: list[BBSection], *,
                 heading_template: str = DEFAULT_HEADING_TEMPLATE,
                 media_tag: str = "IMG", custom_media_tag: str = "") -> str:
    """Compose the whole BB-code post. / Собрать весь BB-код публикации."""
    lines = [heading_template.format(title=title.strip())]
    for section in sections:
        name = section.name.strip()
        links = [link for link in section.links if link]
        if not links:
            continue
        lines.append("")
        lines.append(f"[B]{name}[/B]")
        lines.append("[spoiler]")
        lines.extend(format_media(link, media_tag, custom_media_tag) for link in links)
        lines.append("[/spoiler]")
    return "\n".join(lines).rstrip("\n") + "\n"
