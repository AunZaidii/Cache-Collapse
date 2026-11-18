import re, sys, html
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
import os
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                                ListFlowable, ListItem, Preformatted, Table, TableStyle,
                                Image, KeepTogether)
from reportlab.lib.utils import ImageReader
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT

SRC = sys.argv[1]
OUT = sys.argv[2]

NAVY = colors.HexColor("#1f3a5f")
TEAL = colors.HexColor("#0f7b7b")
GOLD = colors.HexColor("#d98c1f")
GREY = colors.HexColor("#444444")

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20, textColor=NAVY,
                    spaceBefore=6, spaceAfter=10, leading=24)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14, textColor=TEAL,
                    spaceBefore=14, spaceAfter=6, leading=18)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=11.5, textColor=NAVY,
                    spaceBefore=8, spaceAfter=4, leading=15)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=15,
                      textColor=GREY, alignment=TA_LEFT, spaceAfter=4)
ITAL = ParagraphStyle("Ital", parent=BODY, fontSize=9.5, textColor=colors.HexColor("#666666"))
BULLET = ParagraphStyle("Bul", parent=BODY, leftIndent=4)
CODE = ParagraphStyle("Code", parent=styles["Code"], fontName="Courier", fontSize=6.3,
                      leading=7.6, textColor=colors.HexColor("#243447"))
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)
CELLH = ParagraphStyle("CellH", parent=CELL, textColor=colors.white, fontName="Helvetica-Bold")
CAP = ParagraphStyle("Cap", parent=ITAL, fontSize=9, alignment=1, spaceBefore=4, spaceAfter=10,
                     textColor=colors.HexColor("#777777"))
SRCDIR = os.path.dirname(os.path.abspath(SRC))
MAXW = 170 * mm


def inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r'<font face="Courier" color="#b5306b">\1</font>', t)
    return t


def build(src):
    lines = src.split("\n")
    story = []
    i = 0
    pending = []  # (type, text) for list buffering

    def flush_list():
        nonlocal pending
        if not pending:
            return
        items = []
        for _typ, txt in pending:
            items.append(ListItem(Paragraph(inline(txt), BULLET), leftIndent=14))
        bt = "1" if pending[0][0] == "ol" else "bullet"
        story.append(ListFlowable(items, bulletType=bt,
                                  bulletColor=GOLD, bulletFontSize=9,
                                  leftIndent=16, spaceAfter=6))
        pending = []

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush_list(); i += 1; continue
        # image  ![alt](path)
        mimg = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", s)
        if mimg:
            flush_list()
            alt, path = mimg.group(1), mimg.group(2).strip()
            ipath = path if os.path.isabs(path) else os.path.join(SRCDIR, path)
            if os.path.exists(ipath):
                iw, ih = ImageReader(ipath).getSize()
                w = min(MAXW, iw * 0.5)
                h = w * ih / iw
                flow = [Image(ipath, width=w, height=h)]
                if alt:
                    flow.append(Paragraph(inline(alt), CAP))
                story.append(KeepTogether(flow))
            else:
                story.append(Paragraph("[missing image: %s]" % html.escape(path), ITAL))
            i += 1
            continue
        # fenced code block
        if s.startswith("```"):
            flush_list()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip("\n"))
                i += 1
            i += 1  # skip closing fence
            code = "\n".join(buf) if buf else " "
            story.append(Table([[Preformatted(code, CODE)]],
                               style=TableStyle([
                                   ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f6fa")),
                                   ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7dee7")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])))
            story.append(Spacer(1, 6))
            continue
        # markdown table
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[i+1]):
            flush_list()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows]
            if len(cells) >= 2 and re.match(r"^[\s:-]+$", "".join(cells[1])):
                header = cells[0]
                body = cells[2:]
                data = [[Paragraph(inline(c), CELLH) for c in header]]
                for r in body:
                    data.append([Paragraph(inline(c), CELL) for c in r])
                ncol = len(header)
                avail = 170 * mm
                tbl = Table(data, colWidths=[avail / ncol] * ncol, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dee7")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
                story.append(tbl)
                story.append(Spacer(1, 8))
            continue
        if s.startswith("# "):
            flush_list(); story.append(Paragraph(inline(s[2:]), H1))
            story.append(HRFlowable(width="100%", thickness=2, color=GOLD,
                                    spaceBefore=2, spaceAfter=8))
        elif s.startswith("## "):
            flush_list(); story.append(Paragraph(inline(s[3:]), H2))
        elif s.startswith("### "):
            flush_list(); story.append(Paragraph(inline(s[4:]), H3))
        elif s.startswith("---"):
            flush_list(); story.append(HRFlowable(width="100%", thickness=0.6,
                                        color=colors.HexColor("#cccccc"),
                                        spaceBefore=6, spaceAfter=6))
        elif re.match(r"^[-*]\s+", s):
            pending.append(("ul", re.sub(r"^[-*]\s+", "", s)))
        elif re.match(r"^\d+\.\s+", s):
            pending.append(("ol", re.sub(r"^\d+\.\s+", "", s)))
        elif s.startswith("*") and s.endswith("*") and len(s) > 2:
            flush_list(); story.append(Paragraph(inline(s), ITAL))
        else:
            flush_list(); story.append(Paragraph(inline(s), BODY))
        i += 1
    flush_list()
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(20*mm, 12*mm, "CacheCollapse · SE-401 Information Security · CEP")
    canvas.drawRightString(190*mm, 12*mm, "Page %d" % doc.page)
    canvas.setStrokeColor(colors.HexColor("#dddddd"))
    canvas.line(20*mm, 15*mm, 190*mm, 15*mm)
    canvas.restoreState()


with open(SRC, encoding="utf-8") as f:
    src = f.read()

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=20*mm, bottomMargin=22*mm,
                        leftMargin=20*mm, rightMargin=20*mm,
                        title="CacheCollapse Specification",
                        author="CacheCollapse Project Group (SE-401)")
doc.build(build(src), onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
