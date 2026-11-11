"""The one rule for markup that the HTML readers refuse, applied to the text before html.parser reads it.

A marked section, markup that opens with "<![", is read only when its name is CDATA, TEMP, IGNORE, INCLUDE or RCDATA, or
IF, ELSE or ENDIF as conditional comments use it (in any case, and the whole name: "<![ifx" is not IF). Any other, such
as "<![bogus[" or "<![ x", makes the whole markup unreadable, wherever it stands; escaped text ("&lt;![") is text, not
markup. These are the sections Python 3.12.8's html.parser read; it refused the others by raising AssertionError. From a
later patch release on (3.12.16 at least) the parser reads every input as HTML5 does and drops such a section, its text
included, as a comment, and it also reads title, textarea and iframe contents differently, so a rule that followed the
parser's own reading would not give the same answer under both. The rule reads only the text, so it does.
"""
import re

SECTIONS = ("CDATA", "TEMP", "IGNORE", "INCLUDE", "RCDATA", "IF", "ELSE", "ENDIF")
_OTHER_SECTION = re.compile(r"<!\[(?!(?:%s)(?![-_.A-Za-z0-9]))" % "|".join(SECTIONS), re.IGNORECASE | re.ASCII)


def unreadable(text: str) -> bool:
    """Whether the text holds a marked section the readers do not read."""
    return _OTHER_SECTION.search(text) is not None
