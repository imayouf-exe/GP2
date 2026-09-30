import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher


def parse_natural_datetime(date_text, time_text=None):
    """Parse simple natural date/time phrases into datetime."""
    now = datetime.now()
    date_val = (date_text or "").strip().lower()
    time_val = (time_text or "").strip().lower()
    target_date = now.date()
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }

    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_val):
        target_date = datetime.strptime(date_val, "%Y-%m-%d").date()
    elif date_val == "today" or not date_val:
        target_date = now.date()
    elif date_val == "tomorrow":
        target_date = (now + timedelta(days=1)).date()
    elif date_val.startswith("next "):
        wd = date_val.replace("next ", "").strip()
        if wd in weekdays:
            diff = (weekdays[wd] - now.weekday()) % 7
            diff = 7 if diff == 0 else diff
            target_date = (now + timedelta(days=diff)).date()
    elif date_val in weekdays:
        diff = (weekdays[date_val] - now.weekday()) % 7
        target_date = (now + timedelta(days=diff)).date()

    hour, minute = 9, 0
    if time_val:
        m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", time_val)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            mer = m.group(3)
            if mer == "pm" and hour < 12:
                hour += 12
            if mer == "am" and hour == 12:
                hour = 0
            hour = max(0, min(hour, 23))
            minute = max(0, min(minute, 59))

    return datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute, second=0)


def extract_kv_command(message, prefix):
    """Parse command like: 'prefix: key=value, key=value'."""
    text = message.strip()
    if not text.lower().startswith(prefix.lower()):
        return None
    payload = text.split(":", 1)[1] if ":" in text else ""
    parts = [p.strip() for p in payload.split(",") if p.strip()]
    out = {}
    for p in parts:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        out[k.strip().lower()] = v.strip()
    return out


def normalize_message(text):
    """Normalize user text for intent matching."""
    t = (text or "").lower()
    t = t.replace("’", "'").replace("`", "'")
    t = re.sub(r"[^a-z0-9:\-_=#\s']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def any_match(text, patterns):
    """Return True if any regex pattern matches text."""
    return any(re.search(p, text, re.I) for p in patterns)


def fuzzy_contains(text, phrase, threshold=0.86):
    """Approximate substring match for minor typos."""
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    n = len(phrase_tokens)
    if n == 0 or len(text_tokens) < n:
        return False
    target = " ".join(phrase_tokens)
    for i in range(0, len(text_tokens) - n + 1):
        window = " ".join(text_tokens[i:i + n])
        if SequenceMatcher(None, window, target).ratio() >= threshold:
            return True
    return False


def intent_with_typos(text, patterns=None, fuzzy_phrases=None):
    if patterns and any_match(text, patterns):
        return True
    if fuzzy_phrases:
        return any(fuzzy_contains(text, p) for p in fuzzy_phrases)
    return False


def extract_room_from_text(text):
    m = re.search(r"(?:room|classroom)\s*#?\s*([a-z]?\d{2,5})\b", text, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([a-z]?\d{3,5})\b", text, re.I)
    return m.group(1).upper() if m else None


def extract_date_hint(text):
    if "tomorrow" in text:
        return "tomorrow"
    if "today" in text:
        return "today"
    wd = re.search(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", text, re.I)
    if wd:
        return wd.group(0).lower()
    return "today"


def extract_time_range_from_text(text, default_start="9am", default_end="11am"):
    txt = (text or "").lower().strip()

    # "from 2pm to 4pm", "between 2 and 4 pm", "2-4pm", "2:30 to 4"
    m = re.search(
        r"(?:from|between)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|and|-|–)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        txt,
        re.I,
    )
    if m:
        h1, m1, mer1, h2, m2, mer2 = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        # Carry AM/PM if only one side includes it (e.g., "2 to 4pm")
        if mer1 and not mer2:
            mer2 = mer1
        if mer2 and not mer1:
            mer1 = mer2
        start_text = f"{h1}{':' + m1 if m1 else ''}{mer1 or ''}".strip()
        end_text = f"{h2}{':' + m2 if m2 else ''}{mer2 or ''}".strip()
        return start_text, end_text

    # "at 3pm" -> infer one-hour window
    at_match = re.search(r"\bat\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", txt, re.I)
    if at_match:
        h = int(at_match.group(1))
        mm = int(at_match.group(2) or 0)
        mer = (at_match.group(3) or "").lower()
        if mer == "pm" and h < 12:
            h += 12
        if mer == "am" and h == 12:
            h = 0
        end_h = (h + 1) % 24
        start_text = f"{h:02d}:{mm:02d}"
        end_text = f"{end_h:02d}:{mm:02d}"
        return start_text, end_text

    return default_start, default_end


def extract_course_from_message(message_l, courses):
    """Match course by normalized code with basic typo tolerance."""
    compact = message_l.upper().replace(" ", "")
    course_pairs = []
    for c in courses:
        code = (c.get("course_code") or "").upper().replace(" ", "")
        if code:
            course_pairs.append((code, c))

    for code, course in course_pairs:
        if code in compact:
            return course

    tokens = [t.replace(" ", "") for t in re.findall(r"[A-Z]{2,5}\s*\d{3,4}[A-Z]?", message_l.upper())]
    if not tokens:
        return None

    for token in tokens:
        for code, course in course_pairs:
            if token == code:
                return course

    best_course = None
    best_ratio = 0.0
    second_ratio = 0.0
    for token in tokens:
        for code, course in course_pairs:
            ratio = SequenceMatcher(None, token, code).ratio()
            if ratio > best_ratio:
                second_ratio = best_ratio
                best_ratio = ratio
                best_course = course
            elif ratio > second_ratio:
                second_ratio = ratio
    # Guardrail: if two candidates are too close, require clarification instead of guessing.
    if best_course is not None and best_ratio >= 0.86 and (best_ratio - second_ratio) >= 0.04:
        return best_course
    return None


def format_actionable_events(events):
    if not events:
        return "You have no upcoming events in the next 14 days."
    lines = []
    for ev in events:
        line = f"- {ev.get('event_type', 'event').upper()}: {ev.get('title', 'Untitled')}"
        if ev.get("start_fmt"):
            line += f" | Start: {ev['start_fmt']}"
        if ev.get("end_fmt"):
            line += f" | End: {ev['end_fmt']}"
        if ev.get("course"):
            line += f" | Course: {ev['course']}"
        if ev.get("location"):
            line += f" | Location: {ev['location']}"
        if ev.get("description"):
            line += f" | Details: {ev['description']}"
        lines.append(line)
    return "\n".join(lines)
