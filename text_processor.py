import re

# ── Ordinal → digit mapping ─────────────────────────────────────────
ORDINALS = {
    "first": "1", "second": "2", "third": "3", "fourth": "4",
    "fifth": "5", "sixth": "6", "seventh": "7", "eighth": "8",
    "ninth": "9", "tenth": "10",
}


def remove_fillers(text):
    """Remove filler words like um, uh, you know, so, well, etc."""
    # Standalone fillers anywhere in text
    fillers = [
        r"\buh huh\b",
        r"\bum\b", r"\buh\b", r"\ber\b", r"\bah\b",
        r"\bhmm+\b", r"\bhm+\b", r"\bmm+\b",
        r"\byou know\b",
        r"\bbasically\b",
        r"\bliterally\b",
        r"\bI guess\b",
        r"\blike\b(?=\s*,)",  # "like," as filler
    ]
    for filler in fillers:
        text = re.sub(filler + r"[,.]?\s*", " ", text, flags=re.IGNORECASE)

    # "So," / "Well," at start of sentences (after . ! ? or start of text)
    text = re.sub(r"(?<=[.!?])\s+(?:So|Well),?\s+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:So|Well),?\s+", "", text, flags=re.IGNORECASE)

    # Trailing "actually" at end of sentence (filler, not correction)
    # e.g. "I want to do things actually." → "I want to do things."
    text = re.sub(r"\s+actually\s*([.!?])", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+actually\s*$", "", text, flags=re.IGNORECASE)

    # Clean up
    text = re.sub(r"\s+", " ", text).strip()
    # Re-capitalize after cleanup
    text = _recapitalize(text)
    return text


def apply_backtrack(text):
    """Handle mid-sentence corrections.

    Sentence-level:
      'I like blue. Actually, I like red.'  → 'I like red.'
      'blah blah scratch that. next part'   → 'next part'

    Word-level:
      'meet at 2 actually 3'               → 'meet at 3'
      'send to John I mean Mike'           → 'send to Mike'
    """
    # ── 1. Clause deletions: "scratch that" etc ──────────────────────
    for marker in [
        r"scratch that",
        r"never mind that",
        r"never mind",
        r"forget that",
        r"delete that",
    ]:
        text = re.sub(
            r"[^.!?]*?\b" + marker + r"\b[,.]?\s*",
            "", text, flags=re.IGNORECASE,
        )

    # ── 2. Sentence-level: "X. Actually, Y" → "Y" ───────────────────
    #    "Actually" / "I mean" after a sentence boundary replaces the
    #    previous sentence entirely.
    for marker in [r"Actually", r"I mean", r"No wait"]:
        # Match: [previous sentence ending with .!?] [space] [Marker,] [space]
        pattern = r"[^.!?]+[.!?]\s*" + marker + r",?\s+"
        prev = None
        while prev != text:
            prev = text
            text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE)

    # ── 3. Word-level: "X actually Y" → "Y" (mid-sentence) ──────────
    #    Remove only 1 word immediately before the marker.
    #    "meet at 2 actually 3" → "meet at 3"
    for marker in ["actually", "i mean", "no wait"]:
        pattern = r"\S+[\s,]+" + re.escape(marker) + r",?\s+"
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip()
    text = _recapitalize(text)
    return text


def format_numbered_lists(text):
    """Format spoken numbered lists into actual newline-separated lists.

    Handles both digit-based and ordinal-based lists:
      '1. apples 2. bananas 3. oranges'
      'The first one is apples. Second one is bananas.'
      'first, we do X. second, we do Y.'
    """
    # ── Try ordinal-based lists first ────────────────────────────────
    # Build pattern for ordinal markers like:
    #   "the first one is", "first,", "first:", "second one is", "and third one,"
    ordinal_names = "|".join(ORDINALS.keys())
    # Pattern: optional "and/the" + ordinal + optional "one/point/thing" + optional "is/:" + separator
    ordinal_marker = (
        r"(?:And\s+|The\s+)?"           # optional leading "And" / "The"
        r"(?:" + ordinal_names + r")"    # ordinal word
        r"(?:\s+(?:one|point|thing))?"   # optional "one", "point", "thing"
        r"(?:\s+is|,|:)?\s*"            # optional "is" / "," / ":"
    )

    # Find all ordinal matches
    matches = list(re.finditer(ordinal_marker, text, re.IGNORECASE))

    # Only format if at least 2 ordinal items found
    ordinal_matches = []
    for m in matches:
        # Extract which ordinal this is
        for word, num in ORDINALS.items():
            if re.search(r"\b" + word + r"\b", m.group(), re.IGNORECASE):
                ordinal_matches.append((m, num))
                break

    if len(ordinal_matches) >= 2:
        # Rebuild text with numbered list formatting
        result_parts = []
        last_end = 0

        for i, (match, num) in enumerate(ordinal_matches):
            # Text before this ordinal marker
            before = text[last_end:match.start()]
            if i == 0:
                # Keep intro text, add newline before list
                before = before.rstrip()
                if before:
                    result_parts.append(before)
            else:
                # Content of the previous list item - trim trailing period/space
                before = before.rstrip(". ")
                if result_parts:
                    result_parts[-1] = result_parts[-1] + " " + before if before else result_parts[-1]

            result_parts.append(f"\n{num}.")
            last_end = match.end()

        # Remaining text after last marker (last item content)
        remaining = text[last_end:].rstrip(". ") if last_end < len(text) else ""
        if remaining and result_parts:
            result_parts[-1] = result_parts[-1] + " " + remaining

        text = "".join(result_parts).strip()
        return text

    # ── Digit-based lists: "1. X 2. Y 3. Z" ─────────────────────────
    if re.search(r"\b1\.", text) and re.search(r"\b2\.", text):
        text = re.sub(r"\s+(\d+)\.\s+", r"\n\1. ", text)

    return text.strip()


def apply_smart_punctuation(text):
    """Convert dictated punctuation words to actual punctuation marks."""
    replacements = [
        (r"\bcomma\b", ","),
        (r"\bperiod\b", "."),
        (r"\bfull stop\b", "."),
        (r"\bquestion mark\b", "?"),
        (r"\bexclamation mark\b", "!"),
        (r"\bexclamation point\b", "!"),
        (r"\bcolon\b", ":"),
        (r"\bsemicolon\b", ";"),
        (r"\bnew line\b", "\n"),
        (r"\bnewline\b", "\n"),
        (r"\bnew paragraph\b", "\n\n"),
        (r"\bopen quote\b", '"'),
        (r"\bclose quote\b", '"'),
        (r"\bopen paren\b", "("),
        (r"\bclose paren\b", ")"),
        (r"\bhyphen\b", "-"),
        (r"\bdash\b", "\u2014"),
        (r"\bellipsis\b", "..."),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    # Clean up spaces around punctuation
    text = re.sub(r"\s+([.,!?;:)\]])", r"\1", text)
    text = re.sub(r"([\[(])\s+", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def process_text(
    text,
    remove_fillers_on=True,
    backtrack_on=True,
    numbered_lists_on=True,
    smart_punctuation_on=True,
):
    """Apply all enabled text processing in the correct order."""
    if not text:
        return text
    if backtrack_on:
        text = apply_backtrack(text)
    if remove_fillers_on:
        text = remove_fillers(text)
    if smart_punctuation_on:
        text = apply_smart_punctuation(text)
    if numbered_lists_on:
        text = format_numbered_lists(text)
    return text


# ── Helpers ──────────────────────────────────────────────────────────

def _recapitalize(text):
    """Capitalize first letter and first letter after sentence boundaries."""
    if not text:
        return text
    # Capitalize start
    text = text[0].upper() + text[1:] if text else text
    # Capitalize after . ! ?
    text = re.sub(
        r"([.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        text,
    )
    return text
