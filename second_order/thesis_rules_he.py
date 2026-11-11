"""Hebrew claim-word and price-direction rules: the same groups as thesis_rules, matched on normalised Hebrew text.

Niqqud and cantillation are removed and the maqaf becomes a space. A listed form matches as a whole word, with up to
three of the prefix letters in front of it (buy and sell take only ו and ש).
"""
import re

PREFIXES = "והבכלמש"
TRADE_PREFIXES = "וש"
CLAIM_FORMS = {
    "confirm": ("אישש", "איששה", "איששו", "מאשש", "מאששת", "מאששים", "מאששות", "לאשש", "אישוש", "אושש", "אוששה"),
    "prove": ("הוכיח", "הוכיחה", "הוכיחו", "מוכיח", "מוכיחה", "מוכיחים", "מוכיחות", "יוכיח", "תוכיח", "להוכיח",
              "הוכחה", "הוכחות", "מוכח", "מוכחת"),
    "cause": ("גרם", "גרמה", "גרמו", "גורם", "גורמת", "גורמים", "גורמות", "יגרום", "תגרום", "יגרמו", "לגרום",
              "גרימה", "סיבתי", "סיבתית", "סיבתיים", "סיבתיות"),
    "signal": ("איתות", "איתותים", "איתת", "איתתה", "מאותת", "מאותתת", "מאותתים"),
    "recommend": ("ממליץ", "ממליצה", "ממליצים", "ממליצות", "המליץ", "המליצה", "המליצו", "להמליץ", "המלצה", "המלצת",
                  "המלצות"),
    "forecast": ("תחזית", "תחזיות", "לחזות", "ניבוי", "מנבא", "מנבאת", "מנבאים", "ינבא"),
}
TRADE_FORMS = ("קנה", "קנו", "לקנות", "קנייה", "קניה", "מכור", "מכרו", "למכור")
CONFIRM_THESIS = ("מאשר", "מאשרת", "מאשרים", "מאשרות", "אישר", "אישרה", "אישרו")
CONFIRM_OBJECTS = ("התזה", "הסיבה", "הסיכון")
ABSENCE = ("לא קיים", "לא קיימת", "לא קיימים", "לא קיימות", "אינו קיים", "אינה קיימת", "אינם קיימים")
PRICE_PHRASES = ("מחיר יעד", "שווי הוגן", "אפסייד", "דאונסייד", "שורי", "שורית", "דובי", "דובית", "ראלי",
                 "מתומחר ביתר", "מתומחרת ביתר", "מתומחר בחסר", "מתומחרת בחסר", "בהערכת יתר", "בהערכת חסר",
                 "תמחור שגוי")
PRICE_WORDS = ("מחיר", "מחירים", "מחירי", "תמחור")
DIRECTION_WORDS = ("עולה", "עולים", "עולות", "עלה", "עלתה", "עלו", "יעלה", "תעלה", "יעלו", "לעלות", "עלייה", "עליה",
                   "עליות", "עליית", "יורד", "יורדת", "יורדים", "יורדות", "ירד", "ירדה", "ירדו", "ירידה", "ירידות",
                   "ירידת", "זינק", "זינוק", "מזנק", "יזנק", "קפץ", "קפיצה", "צנח", "צניחה", "צונח", "קרס", "קריסה",
                   "התרסק", "טיפס", "טיפוס", "מטפס", "התחזק", "התחזקות", "נחלש", "היחלשות", "לחץ", "לחצים", "תמיכה",
                   "הדוק", "התהדקות")
DIRECTION_PHRASES = ("כלפי מעלה", "כלפי מטה")
COMPARATIVES = ("גבוה", "גבוהה", "גבוהים", "גבוהות", "נמוך", "נמוכה", "נמוכים", "נמוכות")
WINDOW = 5

_MARKS = re.compile("[֑-ׇ]")


def normalise(text: str) -> str:
    return _MARKS.sub("", text.replace("־", " "))


def _alt(forms) -> str:
    return "|".join(re.escape(form).replace("\\ ", r"\s+") for form in sorted(forms, key=len, reverse=True))


def _word(forms, prefixes: str = PREFIXES) -> re.Pattern:
    return re.compile(rf"(?<!\w)[{prefixes}]{{0,3}}(?:{_alt(forms)})(?!\w)")


_CLAIMS = [_word(forms) for forms in CLAIM_FORMS.values()]
_CLAIMS.append(_word(TRADE_FORMS, TRADE_PREFIXES))
_CLAIMS.append(_word(ABSENCE))
_CLAIMS.append(re.compile(
    rf"(?<!\w)[{PREFIXES}]{{0,3}}(?:{_alt(CONFIRM_THESIS)})\s+את\s+(?:{_alt(CONFIRM_OBJECTS)})(?!\w)"))
_PHRASES = _word(PRICE_PHRASES)
_PRICE = _word(PRICE_WORDS)
_DIRECTION = re.compile("|".join([_word(DIRECTION_WORDS).pattern, _word(DIRECTION_PHRASES).pattern,
                                  _word([f"{form} יותר" for form in COMPARATIVES]).pattern]))


def claim_word(text: str) -> str | None:
    """The earliest claim-word match (prefix letters included), or None."""
    text = normalise(text)
    found = [m for m in (pattern.search(text) for pattern in _CLAIMS) if m]
    return min(found, key=lambda m: m.start()).group(0) if found else None


def price_direction(text: str) -> str | None:
    """A price-direction phrase, or a price word with a direction word within five words either side."""
    text = normalise(text)
    phrase = _PHRASES.search(text)
    if phrase:
        return phrase.group(0)
    words = list(re.finditer(r"\w+", text))
    for index, word in enumerate(words):
        if not _PRICE.fullmatch(word.group(0)):
            continue
        before = words[max(0, index - WINDOW):index]
        after = words[index + 1:index + 1 + WINDOW]
        for side in (before, after):
            if side:
                found = _DIRECTION.search(text[side[0].start():side[-1].end()])
                if found:
                    return f"{word.group(0)} ... {found.group(0)}"
    return None
