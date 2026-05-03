"""PEP 701 compatibility scanner.

Uses tokenize to pick out FSTRING_START tokens only (so regular
string literals aren't misinterpreted as f-string prefixes), then
examines the corresponding FSTRING_MIDDLE / expression tokens for
patterns the Python 3.11 tokenizer rejects:

  * inner quote matching the outer delimiter
  * backslash anywhere in the expression
  * literal newline inside a single-line f-string expression

Run with:  python tools/scan_pep701.py
Exits 0 when clean, 1 when issues are found.
"""
from __future__ import annotations

import io
import os
import sys
import tokenize

BS = chr(92)
NL = chr(10)


def scan_file(path: str) -> list[str]:
    issues: list[str] = []
    with open(path, "rb") as fh:
        try:
            tokens = list(tokenize.tokenize(fh.readline))
        except tokenize.TokenizeError as exc:
            issues.append(f"{path}: tokenize error: {exc}")
            return issues
        except SyntaxError as exc:
            issues.append(f"{path}: syntax error: {exc}")
            return issues

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type != tokenize.FSTRING_START:
            i += 1
            continue
        # The FSTRING_START token string is the prefix + opening quotes,
        # e.g. `f"`, `f"""`, `rf'`, etc.  Extract the quote character(s).
        start_str = tok.string
        # Strip the prefix letters; last 1 or 3 chars are quotes.
        quotes_only = start_str.lstrip("fFrRbBuU")
        q = quotes_only[0] if quotes_only else '"'
        triple = len(quotes_only) >= 3 and quotes_only[:3] == q * 3

        f_start_line = tok.start[0]
        j = i + 1
        in_expr = False
        expr_start_line = None
        while j < len(tokens):
            inner = tokens[j]
            if inner.type == tokenize.FSTRING_END:
                break
            if inner.type == tokenize.FSTRING_MIDDLE:
                j += 1
                continue
            if inner.type == tokenize.OP and inner.string == "{":
                in_expr = True
                expr_start_line = inner.start[0]
                j += 1
                continue
            if inner.type == tokenize.OP and inner.string == "}":
                in_expr = False
                expr_start_line = None
                j += 1
                continue
            if in_expr:
                text = inner.string
                if q in text and inner.type in (tokenize.STRING,):
                    # A nested string literal using the same quote char.
                    issues.append(
                        f"{path}:{expr_start_line}: "
                        f"f-string expr uses nested {q!r}-quoted string"
                    )
                if BS in text:
                    issues.append(
                        f"{path}:{expr_start_line}: "
                        f"f-string expr contains backslash"
                    )
                if NL in text and not triple:
                    issues.append(
                        f"{path}:{expr_start_line}: "
                        f"multi-line f-string expr"
                    )
            j += 1
        i = j + 1
    return issues


def main() -> int:
    all_issues: list[str] = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [
            d for d in dirs
            if d not in (".git", "node_modules", "__pycache__",
                         "frontend", "dist", "build", ".superpowers",
                         ".venv", "venv", "env")
        ]
        for f in files:
            if not f.endswith(".py"):
                continue
            all_issues.extend(scan_file(os.path.join(root, f)))
    for it in all_issues:
        print(it)
    print(f"Total: {len(all_issues)}")
    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
