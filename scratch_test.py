import re

NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)[\.\)]\s*(?:\[([^\]]+)\]\s*)?(.*)$")

def _parse_numbered_reply_items(text, expected_count):
    items = []
    # Replace literal \n and \r with spaces or something? Or maybe split by regular expressions.
    # Let's split by digit dot.
    parts = re.split(r'(?=\b\d+[\.\)])', str(text or "").replace("\r", "\n"))
    for line in parts:
        # replace inner newlines so it matches nicely?
        line = line.replace('\n', ' ').strip()
        match = NUMBERED_ITEM_RE.match(line)
        if not match:
            continue
        value = match.group(3).strip(" -")
        if value:
            items.append({"style_id": (match.group(2) or "").lower(), "content": value})
        if len(items) >= expected_count:
            break
    return items

text = "1. [supportive] Totally agree, it's a really smart take on the whole crypto landscape. 2. [supportive] I've been trying to wrap my head around some of this stuff, and this tweet actually made it click for me. 3. [supportive] Yeah, it's refreshing to see a clear explanation of the tradeoffs involved with different crypto approaches."

print(_parse_numbered_reply_items(text, 3))
