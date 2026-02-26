from django import template

register = template.Library()


@register.filter
def initials(value):
    text = str(value or "").strip()
    if not text:
        return "U"

    normalized = text.replace("_", " ").replace("-", " ")
    parts = [part for part in normalized.split() if part]

    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()

    cleaned = "".join(ch for ch in parts[0] if ch.isalnum()) if parts else ""
    if not cleaned:
        return "U"

    return cleaned[:2].upper()
