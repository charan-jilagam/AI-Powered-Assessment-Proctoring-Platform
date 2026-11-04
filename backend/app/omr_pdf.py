"""OMR answer sheets as PDF (A4, vector, prints cleanly on any printer).

One :class:`OmrSheet` is one candidate's sheet (or one blank template). ``render`` draws any number of them into a
single PDF, starting each on a fresh page. The layout is deterministic and has no database access, so it is tested
by rendering and reading the PDF back.

Sheet anatomy: alignment marks in the four corners, institute header, candidate / test details, the set bubbles,
instructions, the bubble grid (questions numbered down each column, in blocks of five rows) and signature boxes. An
*evaluated* copy additionally colours each mark (green right, red wrong), rings the right answer and prints the score.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from reportlab.lib.colors import Color, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4
MARGIN = 34.0                       # content margin; the alignment marks sit just outside it
CONTENT_W = PAGE_W - 2 * MARGIN
GROUP = 5                           # rows per block
GROUP_GAP = 5.0

INK = Color(0.10, 0.12, 0.16)
MUTED = Color(0.40, 0.43, 0.48)
LINE = Color(0.62, 0.65, 0.70)
FAINT = Color(0.93, 0.94, 0.96)
GREEN = Color(0.10, 0.55, 0.28)
RED = Color(0.80, 0.15, 0.15)
BAND = Color(0.12, 0.16, 0.24)

FONT, BOLD = "Helvetica", "Helvetica-Bold"


@dataclass
class OmrQuestion:
    number: int
    kind: str                                   # single | multiple | true_false | short_text
    labels: List[str] = field(default_factory=list)          # bubble letters, e.g. A B C D  (T F for true/false)
    marked: List[int] = field(default_factory=list)          # indexes the candidate filled
    correct: Optional[List[int]] = None                      # evaluated copies only
    text: Optional[str] = None                               # short-text answer typed by the candidate
    correct_text: Optional[str] = None                       # evaluated copies only
    verdict: Optional[str] = None                            # correct | wrong | blank (evaluated copies only)


@dataclass
class OmrSheet:
    institute: str
    test_title: str
    questions: List[OmrQuestion]
    note: str = ""
    test_code: str = ""
    candidate_name: str = ""
    email: str = ""
    phone: str = ""
    extras: List[Tuple[str, str]] = field(default_factory=list)   # (label, value) from the test's custom fields
    date_text: str = ""
    time_text: str = ""
    duration_text: str = ""
    attempt_ref: str = ""
    set_letter: str = ""                                     # "" when the test has no sets
    set_letters: str = ""                                    # every set of the test, e.g. "ABC"
    evaluated: bool = False
    blank: bool = False                                      # an empty template to print and hand out
    summary: Optional[Dict[str, object]] = None              # evaluated copies: score, max, percentage, correct, wrong, blank, result
    generated_text: str = ""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _t(text: object) -> str:
    """Helvetica can only draw Latin-1; anything else becomes '?' rather than garbage."""
    return str(text or "").encode("latin-1", "replace").decode("latin-1")


def _fit(text: str, font: str, size: float, width: float, min_size: float = 6.0) -> Tuple[str, float]:
    text = _t(text)
    while size > min_size and stringWidth(text, font, size) > width:
        size -= 0.5
    if stringWidth(text, font, size) > width:
        while text and stringWidth(text + "...", font, size) > width:
            text = text[:-1]
        text += "..."
    return text, size


def _text(c, x, y, text, font=FONT, size=9, color=INK, width=None, align="left"):
    if width is not None:
        text, size = _fit(text, font, size, width)
    else:
        text = _t(text)
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "center":
        c.drawCentredString(x, y, text)
    elif align == "right":
        c.drawRightString(x, y, text)
    else:
        c.drawString(x, y, text)


def _bubble(c, cx, cy, r, label, state):
    """state: empty | filled | right | wrong | key  (key = the right answer the candidate did not mark)."""
    if state in ("filled", "right", "wrong"):
        c.setFillColor({"filled": black, "right": GREEN, "wrong": RED}[state])
        c.setStrokeColor({"filled": black, "right": GREEN, "wrong": RED}[state])
        c.setLineWidth(0.8)
        c.circle(cx, cy, r, stroke=1, fill=1)
        label_color = white
    else:
        c.setFillColor(white)
        c.setStrokeColor(GREEN if state == "key" else LINE)
        c.setLineWidth(1.8 if state == "key" else 0.8)
        c.circle(cx, cy, r, stroke=1, fill=1)
        label_color = GREEN if state == "key" else MUTED
    size = r * 1.05
    c.setFillColor(label_color)
    c.setFont(BOLD if state != "empty" else FONT, size)
    c.drawCentredString(cx, cy - size * 0.34, label)


def _box(c, x, y, w, h, label, value="", blank=False, value_size=9.5):
    """A labelled field; ``y`` is the TOP edge."""
    c.setStrokeColor(LINE)
    c.setLineWidth(0.7)
    c.setFillColor(white)
    c.roundRect(x, y - h, w, h, 2.5, stroke=1, fill=1)
    _text(c, x + 5, y - 8.5, label.upper(), BOLD, 5.8, MUTED, width=w - 10)
    if value and not blank:
        _text(c, x + 5, y - h + 6.5, value, BOLD, value_size, INK, width=w - 10)


# ---------------------------------------------------------------------------
# layout planning
# ---------------------------------------------------------------------------
@dataclass
class _Plan:
    cols: int
    row_h: float
    radius: float
    spacing: float
    pages: List[List[List[OmrQuestion]]]        # pages -> columns -> questions
    shorts: List[OmrQuestion]
    shorts_page: int                            # page index that carries the written answers (-1 if none)


FIRST_TOP = 0.0       # filled in by _header (depends on how many info rows the sheet has)


def _rows_that_fit(avail: float, row_h: float) -> int:
    """How many rows fit in ``avail`` points, in whole blocks of GROUP rows (each block adds GROUP_GAP)."""
    block = GROUP * row_h + GROUP_GAP
    return max(0, int(avail // block)) * GROUP


def _plan(sheet: OmrSheet, first_avail: float, next_avail: float, last_reserved: float) -> _Plan:
    grid = [q for q in sheet.questions if q.kind != "short_text"]
    shorts = [q for q in sheet.questions if q.kind == "short_text"]
    most = max((len(q.labels) for q in grid), default=4)
    cols = 4 if most <= 5 else 3
    col_w = CONTENT_W / cols
    spacing = min(22.0, (col_w - 30) / max(most, 1))

    chosen = 17.0
    for candidate in (26.0, 22.0, 19.0, 17.0):
        rows = _rows_that_fit(first_avail - last_reserved, candidate)
        if rows * cols >= len(grid):
            chosen = candidate
            break
    row_h = chosen
    radius = min(7.2, row_h * 0.33, spacing * 0.42)

    pages: List[List[List[OmrQuestion]]] = []
    remaining = list(grid)
    page_no = 0
    while remaining or not pages:
        avail = first_avail if page_no == 0 else next_avail
        cap_rows = _rows_that_fit(avail, row_h) or GROUP
        # the last page also has to leave room for the signatures / summary
        if len(remaining) <= cols * _rows_that_fit(avail - last_reserved, row_h):
            cap_rows = _rows_that_fit(avail - last_reserved, row_h) or GROUP
        take = remaining[: cols * cap_rows]
        remaining = remaining[len(take):]
        rows = -(-len(take) // cols) if take else 0
        columns = [take[k * rows:(k + 1) * rows] for k in range(cols)] if rows else [[] for _ in range(cols)]
        pages.append(columns)
        page_no += 1
        if page_no > 60:   # absolute safety net
            break

    shorts_page = -1
    if shorts:
        shorts_page = len(pages) - 1
        used_rows = max((len(col) for col in pages[-1]), default=0)
        used = used_rows * row_h + (used_rows // GROUP) * GROUP_GAP
        avail = first_avail if len(pages) == 1 else next_avail
        need = 22 + 15 * len(shorts)
        if avail - last_reserved - used < need:
            pages.append([[] for _ in range(cols)])
            shorts_page = len(pages) - 1
    return _Plan(cols, row_h, radius, spacing, pages, shorts, shorts_page)


# ---------------------------------------------------------------------------
# page furniture
# ---------------------------------------------------------------------------
def _corner_marks(c):
    c.setFillColor(black)
    for x, y in ((14, 14), (PAGE_W - 24, 14), (14, PAGE_H - 24), (PAGE_W - 24, PAGE_H - 24)):
        c.rect(x, y, 10, 10, stroke=0, fill=1)


def _footer(c, sheet: OmrSheet, page: int, pages: int):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, 30, PAGE_W - MARGIN, 30)
    left = f"ORVEXA  |  {sheet.attempt_ref}" if sheet.attempt_ref else "ORVEXA"
    if sheet.generated_text:
        left += f"  |  {sheet.generated_text}"
    _text(c, MARGIN, 20, left, FONT, 6.5, MUTED, width=CONTENT_W - 80)
    _text(c, PAGE_W - MARGIN, 20, f"Page {page} of {pages}", FONT, 6.5, MUTED, align="right")


def _first_header(c, sheet: OmrSheet) -> float:
    """Draw the full header and return the y where the answer area may start."""
    y = PAGE_H - 36
    name, size = _fit(sheet.institute or "Institute", BOLD, 16, CONTENT_W)
    _text(c, PAGE_W / 2, y - 12, name, BOLD, size, INK, align="center")
    y -= 16
    if sheet.note:
        _text(c, PAGE_W / 2, y - 9, sheet.note, FONT, 8.5, MUTED, width=CONTENT_W, align="center")
        y -= 13
    y -= 10
    # title band
    c.setFillColor(BAND)
    c.roundRect(MARGIN, y - 20, CONTENT_W, 20, 3, stroke=0, fill=1)
    label = "OMR ANSWER SHEET" + ("  -  EVALUATED COPY" if sheet.evaluated else "  -  BLANK TEMPLATE" if sheet.blank else "")
    _text(c, PAGE_W / 2, y - 13.5, label, BOLD, 10.5, white, align="center")
    y -= 20 + 7
    _text(c, MARGIN, y - 8, f"Test: {sheet.test_title}", BOLD, 10, INK, width=CONTENT_W - (150 if sheet.test_code else 0))
    if sheet.test_code:
        _text(c, PAGE_W - MARGIN, y - 8, f"Test code: {sheet.test_code}", BOLD, 9, MUTED, align="right")
    y -= 17

    unit = CONTENT_W / 4
    gap = 4.0
    h = 27.0
    blank = sheet.blank
    has_sets = bool(sheet.set_letters)

    # row 1: candidate name | set
    name_w = unit * 3 - gap if has_sets else CONTENT_W
    _box(c, MARGIN, y, name_w, h, "Candidate name", sheet.candidate_name, blank)
    if has_sets:
        sx = MARGIN + unit * 3
        sw = unit
        _box(c, sx, y, sw, h, "Question set", "", blank)
        letters = sheet.set_letters
        step = min(18.0, (sw - 12) / max(len(letters), 1))
        for i, ch in enumerate(letters):
            cx = sx + 12 + step * i + step / 2 - 6
            _bubble(c, cx, y - h + 9.5, 6.4, ch, "filled" if ch == sheet.set_letter else "empty")
    y -= h + gap
    # row 2: email | phone | code
    _box(c, MARGIN, y, unit * 2 - gap, h, "E-mail", sheet.email, blank)
    _box(c, MARGIN + unit * 2, y, unit - gap, h, "Phone", sheet.phone, blank)
    _box(c, MARGIN + unit * 3, y, unit, h, "Attempt ID" if not blank else "Centre / hall", sheet.attempt_ref.replace("Attempt ", ""), blank)
    y -= h + gap
    # extra candidate fields (roll number ...), 4 per row
    extras = list(sheet.extras) if not blank else [(lbl, "") for lbl, _ in sheet.extras]
    for i in range(0, len(extras), 4):
        row = extras[i:i + 4]
        for k, (lbl, val) in enumerate(row):
            w = unit - gap if k < len(row) - 1 or len(row) == 4 else unit
            _box(c, MARGIN + unit * k, y, w, h, lbl, val, blank)
        y -= h + gap
    # row 3: date / time / duration / questions
    _box(c, MARGIN, y, unit - gap, h, "Date", sheet.date_text, blank)
    _box(c, MARGIN + unit, y, unit - gap, h, "Start time", sheet.time_text, blank)
    _box(c, MARGIN + unit * 2, y, unit - gap, h, "Duration", sheet.duration_text, blank)
    _box(c, MARGIN + unit * 3, y, unit, h, "Questions", str(len(sheet.questions)), False)
    y -= h + 7

    # instructions + legend
    ih = 34.0
    c.setFillColor(FAINT)
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.roundRect(MARGIN, y - ih, CONTENT_W, ih, 3, stroke=1, fill=1)
    if sheet.blank:
        lines = ["Use a black or blue ball-point pen. Darken ONE circle completely for each question; * = more than one answer may be correct.",
                 "Do not tick, cross or half-fill. Do not write inside the grid. Erased or double-marked answers are not counted."]
    elif sheet.evaluated:
        lines = ["Filled circles are the answers the candidate recorded. Green = right, red = wrong, a green ring marks the right answer.",
                 "* = more than one answer may be correct (all must be marked for full marks)."]
    else:
        lines = ["Filled circles are the answers the candidate recorded in the online exam.",
                 "* = more than one answer may be correct."]
    for i, line in enumerate(lines):
        _text(c, MARGIN + 7, y - 12 - i * 11, line, FONT, 7.2, INK, width=CONTENT_W - 150)
    lx = PAGE_W - MARGIN - 122
    if sheet.evaluated:
        items = [("right", "right"), ("wrong", "wrong"), ("key", "answer key"), ("empty", "not marked")]
    else:
        items = [("filled", "marked"), ("empty", "not marked")]
    for i, (state, text) in enumerate(items):
        cx = lx + (i % 2) * 62
        cy = y - 12 - (i // 2) * 14
        _bubble(c, cx, cy, 5.2, "A", state)
        _text(c, cx + 9, cy - 2.4, text, FONT, 6.6, MUTED)
    y -= ih + 9
    return y


def _running_header(c, sheet: OmrSheet) -> float:
    y = PAGE_H - 40
    _text(c, MARGIN, y, sheet.institute, BOLD, 9, INK, width=CONTENT_W * 0.45)
    mid = f"{sheet.test_title}" + (f"  |  Set {sheet.set_letter}" if sheet.set_letter else "")
    _text(c, PAGE_W - MARGIN, y, f"{sheet.candidate_name or 'OMR answer sheet'}  -  {mid}", FONT, 8, MUTED, width=CONTENT_W * 0.55, align="right")
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(MARGIN, y - 6, PAGE_W - MARGIN, y - 6)
    return y - 16


def _bottom_block(c, sheet: OmrSheet):
    """Summary strip (evaluated copies) and the two signature boxes, anchored to the page bottom."""
    y = 40.0 + 36.0
    if sheet.evaluated and sheet.summary:
        s = sheet.summary
        cells = [("Score", f"{s.get('score', 0):g} / {s.get('max', 0):g}"), ("Percentage", f"{s.get('percentage', 0):g}%"),
                 ("Correct", str(s.get("correct", 0))), ("Wrong", str(s.get("wrong", 0))), ("Not attempted", str(s.get("blank", 0))),
                 ("Result", str(s.get("result", "-")))]
        w = CONTENT_W / len(cells)
        for i, (lbl, val) in enumerate(cells):
            _box(c, MARGIN + w * i, y + 34, w - 3, 28, lbl, val, False, 10.5)
    bw = (CONTENT_W - 12) / 2
    for i, lbl in enumerate(("Candidate signature", "Invigilator signature")):
        x = MARGIN + (bw + 12) * i
        c.setStrokeColor(LINE)
        c.setLineWidth(0.7)
        c.setFillColor(white)
        c.roundRect(x, 40, bw, 32, 2.5, stroke=1, fill=1)
        _text(c, x + 5, 40 + 32 - 8.5, lbl.upper(), BOLD, 5.8, MUTED)


def _draw_grid(c, sheet: OmrSheet, plan: _Plan, columns: List[List[OmrQuestion]], top: float):
    col_w = CONTENT_W / plan.cols
    r, sp = plan.radius, plan.spacing
    for k, col in enumerate(columns):
        x0 = MARGIN + k * col_w
        if not col:
            continue
        rows = len(col)
        height = rows * plan.row_h + ((rows - 1) // GROUP) * GROUP_GAP
        # block frame + alternate group shading
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.setFillColor(white)
        c.roundRect(x0 + 1, top - height - 3, col_w - 4, height + 6, 3, stroke=1, fill=0)
        for i, q in enumerate(col):
            row_top = top - i * plan.row_h - (i // GROUP) * GROUP_GAP
            if (i // GROUP) % 2 == 0:
                c.setFillColor(FAINT)
                c.rect(x0 + 2, row_top - plan.row_h, col_w - 6, plan.row_h, stroke=0, fill=1)
            cy = row_top - plan.row_h / 2
            num = f"{q.number}{'*' if q.kind == 'multiple' else ''}"
            _text(c, x0 + 24, cy - 3, num, BOLD, 8.2, INK, align="right")
            bx = x0 + 34 + r
            for idx, label in enumerate(q.labels):
                marked = idx in q.marked
                is_key = bool(sheet.evaluated and q.correct is not None and idx in q.correct)
                if sheet.evaluated:
                    state = ("right" if is_key else "wrong") if marked else ("key" if is_key else "empty")
                else:
                    state = "filled" if marked else "empty"
                _bubble(c, bx + idx * sp, cy, r, label, state)
    return


def _draw_shorts(c, sheet: OmrSheet, plan: _Plan, top: float):
    _text(c, MARGIN, top - 9, "WRITTEN ANSWERS", BOLD, 7.5, MUTED)
    y = top - 14
    for q in plan.shorts:
        y -= 15
        given = q.text or ("(not answered)" if not sheet.blank else "")
        _text(c, MARGIN, y, f"{q.number}.", BOLD, 8.5, INK)
        color = INK
        if sheet.evaluated:
            color = GREEN if q.verdict == "correct" else RED if q.verdict == "wrong" else MUTED
        _text(c, MARGIN + 22, y, given, FONT, 8.5, color, width=CONTENT_W * 0.5)
        if sheet.evaluated and q.correct_text:
            _text(c, MARGIN + CONTENT_W * 0.55, y, f"Accepted: {q.correct_text}", FONT, 7.5, MUTED, width=CONTENT_W * 0.45)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.4)
        c.line(MARGIN + 22, y - 2.5, MARGIN + CONTENT_W * 0.52, y - 2.5)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def _measure_first_header(sheet: OmrSheet) -> float:
    """Height the first-page header takes, found by drawing it on a throw-away canvas."""
    probe = canvas.Canvas(io.BytesIO(), pagesize=A4)
    return PAGE_H - _first_header(probe, sheet)


def render(sheets: Sequence[OmrSheet]) -> bytes:
    if not sheets:
        raise ValueError("No sheets to render")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(f"OMR - {sheets[0].test_title}" if len(sheets) == 1 else f"OMR sheets - {sheets[0].test_title}")
    c.setAuthor("ORVEXA")
    c.setCreator("ORVEXA")
    bottom_reserved = 40.0 + 36.0 + 8.0
    for sheet in sheets:
        summary_extra = 38.0 if (sheet.evaluated and sheet.summary) else 0.0
        head = _measure_first_header(sheet)
        first_avail = PAGE_H - head - 36.0 - 8.0          # to the footer rule, before the signature block
        next_avail = PAGE_H - 56.0 - 36.0 - 8.0
        reserved = bottom_reserved - 36.0 + summary_extra  # signature block (+ summary strip) height
        plan = _plan(sheet, first_avail, next_avail, reserved)
        total = len(plan.pages)
        for p, columns in enumerate(plan.pages):
            _corner_marks(c)
            top = _first_header(c, sheet) if p == 0 else _running_header(c, sheet)
            _draw_grid(c, sheet, plan, columns, top)
            rows_used = max((len(col) for col in columns), default=0)
            used = rows_used * plan.row_h + (max(rows_used - 1, 0) // GROUP) * GROUP_GAP + 8
            if plan.shorts and p == plan.shorts_page:
                _draw_shorts(c, sheet, plan, top - used)
            if p == total - 1:
                _bottom_block(c, sheet)
            _footer(c, sheet, p + 1, total)
            c.showPage()
    c.save()
    return buf.getvalue()
