"""One worksheet of a retained XLSX workbook as {cell: text}, read without trusting the archive (thesis-workbook).

The workbook is read from bytes in memory: nothing is extracted to disk, written or fetched. The archive checks are
this module's own, because a source workbook can hold far more parts than an H.15 release package: 1 to MAX_ENTRIES
entries with distinct, safe names (market_package's rule), no links, no encryption, stored or deflated only, every
declared and actual entry size at most MAX_ENTRY, at most MAX_TOTAL bytes in all, no entry expanding more than
MAX_RATIO:1, and every entry read through once so that its CRC and declared size are checked. XML parts are parsed by
rate_workbook's protected expat parser: DOCTYPE, entity, notation and unparsed-entity declarations are refused,
parameter entities are never parsed and external references are refused, so nothing is expanded, fetched or opened.

The main part is found through the package relationships and each sheet through the workbook's relationships. A
cell's text is its shared string resolved, its inline string read, or, for every other cell (numbers, booleans, formula
results, errors), the raw text the workbook stores, unchanged: nothing is formatted, rounded or converted. A cell whose
type is not a text type (shared string, inline string, formula string) is returned as Number, a str subclass, so a
reader can tell a stored number from text. Empty cells are left out. A failure of anything all sheets share refuses
the workbook (WorkbookRefused); a failure of one sheet's own part refuses that sheet only. Nothing is repaired, skipped
or guessed.
"""
import io
import zipfile
import zlib

from . import rate_workbook
from .market_package import ArchiveRefused, _entry_name_safe, _stream
from .rate_workbook import MAIN, OFFICE_RELS, _Sheet, _Strings, _parse, _relationships, _rels_part

MAX_ENTRIES = 400
MAX_ENTRY = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_RATIO = 200


class WorkbookRefused(ValueError):
    """The workbook failed a check; nothing read from it may be used."""


class Number(str):
    """A number cell's text exactly as the workbook stores it: a cell whose type is none of TEXT_TYPES. It is a str in
    every other respect, so {cell: text} stays plain text; only isinstance(text, Number) tells a stored number from
    text that looks like one."""


TEXT_TYPES = ("s", "inlineStr", "str")  # Shared string, inline string, a formula's string result.


def sheet_cells(raw: bytes, sheet: str) -> dict[str, str]:
    """One worksheet as {cell reference: text}, number cells as Number. Raises WorkbookRefused, also when the workbook
    has no such sheet or that sheet's own part fails a check."""
    found, refused = read_sheets(raw, (sheet,))
    if sheet in refused:
        raise WorkbookRefused(refused[sheet])
    if sheet not in found:
        raise WorkbookRefused(f"The workbook has no sheet named {sheet!r}")
    return found[sheet]


def read_sheets(raw: bytes, sheets) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({sheet: {cell reference: text}} for each named sheet that reads, {sheet: why it was refused} for each named
    sheet whose own part fails a check), from one pass of the archive checks; a named sheet the workbook does not list
    is in neither. Everything shared by all sheets (the archive, the relationships, the sheet list and the shared
    strings) is checked whatever is asked for, and its failure raises WorkbookRefused, so that outcome depends on the
    bytes alone."""
    if not isinstance(raw, (bytes, bytearray)):
        raise WorkbookRefused("A workbook is read from bytes")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            return _read(archive, tuple(dict.fromkeys(sheets)))
    except WorkbookRefused:
        raise
    except rate_workbook.WorkbookRefused as exc:  # The protected parser's refusals, under this module's name.
        raise WorkbookRefused(str(exc)) from None
    except ArchiveRefused as exc:
        raise WorkbookRefused(f"The workbook archive was refused ({exc.outcome}): {exc}") from None
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, ValueError, OSError) as exc:
        raise WorkbookRefused(f"The workbook archive could not be read ({type(exc).__name__}: {exc})") from None


# ---------------------------------------------------------------- the archive

def _infos(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_ENTRIES:
        raise WorkbookRefused(f"The workbook archive has {len(infos)} entries; 1 to {MAX_ENTRIES} are allowed")
    names = [info.filename for info in infos]
    if len(set(names)) != len(names):
        raise WorkbookRefused("The workbook archive holds two entries with the same name")
    declared = 0
    for info in infos:
        name = info.filename
        if not _entry_name_safe(name):
            raise WorkbookRefused(f"The workbook archive has an unsafe entry path {name!r}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise WorkbookRefused(f"Workbook entry {name!r} is a symbolic link")
        if info.flag_bits & 0x1:
            raise WorkbookRefused(f"Workbook entry {name!r} is encrypted")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise WorkbookRefused(f"Workbook entry {name!r} uses unsupported compression {info.compress_type}")
        if not info.is_dir():
            if info.file_size > MAX_ENTRY:
                raise WorkbookRefused(f"Workbook entry {name!r} declares {info.file_size} bytes; the limit is "
                                      f"{MAX_ENTRY}")
            declared += info.file_size
    if declared > MAX_TOTAL:
        raise WorkbookRefused(f"The workbook archive declares {declared} bytes in all; the limit is {MAX_TOTAL}")
    return {info.filename: info for info in infos}


def _read_through(archive: zipfile.ZipFile, infos: dict[str, zipfile.ZipInfo]) -> None:
    """Read every entry once, with this module's limits applied as the bytes arrive; zipfile checks each CRC and
    market_package._stream each declared size."""
    total = 0
    for info in infos.values():
        if info.is_dir():
            continue
        actual = 0
        for chunk in _stream(archive, info, [0]):
            actual += len(chunk)
            total += len(chunk)
            if actual > MAX_ENTRY or total > MAX_TOTAL:
                raise WorkbookRefused(f"Decompressed bytes passed the limit in workbook entry {info.filename!r}")
            if actual > MAX_RATIO * max(info.compress_size, 1):
                raise WorkbookRefused(f"Workbook entry {info.filename!r} expands more than {MAX_RATIO}:1")


def _targets(archive: zipfile.ZipFile, infos: dict, part: str) -> dict[str, tuple[str, str]]:
    """A relationships part as {id: (type's last segment, package path)}; a package-absolute target ("/xl/...")
    names the same path as a relative one."""
    return {key: (kind, target.lstrip("/")) for key, (kind, target) in _relationships(archive, infos, part).items()}


# ---------------------------------------------------------------- the sheets

def _read(archive: zipfile.ZipFile, wanted: tuple[str, ...]) -> tuple[dict, dict]:
    infos = _infos(archive)
    _read_through(archive, infos)
    documents = [target for kind, target in _targets(archive, infos, "_rels/.rels").values()
                 if kind == "officeDocument"]
    if len(documents) != 1:
        raise WorkbookRefused("The workbook's package does not name exactly one main workbook part")
    listed = []

    def book(name, attrs):
        if name == f"{MAIN}|sheet":
            listed.append((attrs.get("name"), attrs.get(f"{OFFICE_RELS}|id")))
    _parse(archive, infos, documents[0], book, lambda name: None, lambda value: None)
    names = [name for name, _ in listed]
    if not names:
        raise WorkbookRefused("The workbook lists no sheets")
    if len(set(names)) != len(names):
        raise WorkbookRefused("The workbook lists one sheet name twice")
    relations = _targets(archive, infos, _rels_part(documents[0]))
    shared = [target for kind, target in relations.values() if kind == "sharedStrings"]
    if len(shared) > 1:
        raise WorkbookRefused("The workbook names more than one shared-strings part")
    strings = _Strings()
    if shared:
        _parse(archive, infos, shared[0], strings.start, strings.end, strings.text)
    found, refused = {}, {}
    for name, identifier in listed:  # From here on a failure belongs to one sheet only.
        if name not in wanted:
            continue
        try:
            kind, target = relations.get(identifier, (None, None))
            if kind != "worksheet":
                raise WorkbookRefused(f"Sheet {name!r} does not point to a worksheet")
            found[name] = _cells(archive, infos, target, strings.values, name)
        except (WorkbookRefused, rate_workbook.WorkbookRefused) as exc:
            refused[name] = str(exc)
    return ({name: found[name] for name in wanted if name in found},
            {name: refused[name] for name in wanted if name in refused})


def _cells(archive: zipfile.ZipFile, infos: dict, part: str, strings: list[str], sheet: str) -> dict[str, str]:
    cells = {}

    def on_row(number, row):
        for column, (kind, _, raw) in row.items():
            if raw is None:
                continue
            reference = f"{column}{number}"
            if kind == "s":
                if not (raw.isascii() and raw.isdigit()) or int(raw) >= len(strings):
                    raise WorkbookRefused(f"Cell {reference} on sheet {sheet!r} names no shared string")
                cells[reference] = strings[int(raw)]
            else:
                cells[reference] = raw if kind in TEXT_TYPES else Number(raw)
    reader = _Sheet(on_row)
    _parse(archive, infos, part, reader.start, reader.end, reader.text)
    return cells
