"""Create the operator documents, clean default-data archive and release zip."""

from html.parser import HTMLParser
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.program.webapp2.profile import load_profile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", W)


def word(tag, parent=None, text=None, **attributes):
    node = ET.Element(f"{{{W}}}{tag}", {f"{{{W}}}{key}": str(value) for key, value in attributes.items()})
    if text is not None:
        node.text = text
    if parent is not None:
        parent.append(node)
    return node


class ManualParser(HTMLParser):
    """Convert this manual's simple HTML blocks to editable Word content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.parts, self.lists = [], [], []
        self.inside = False
        self.skip = 0
        self.capture = None
        self.rows = None
        self.row = None
        self.external_link = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "main":
            self.inside = True
        if not self.inside:
            return
        if tag == "nav":
            self.skip += 1
        if self.skip:
            return
        if tag == "section" and "site-section" in attrs.get("class", ""):
            self.blocks.append(("page", ""))
        if tag in ("ol", "ul"):
            self.lists.append([tag, 0])
        if tag == "table":
            self.rows = []
        if tag == "tr":
            self.row = []
        if tag in ("h1", "h2", "h3", "p", "li", "th", "td"):
            self.capture, self.parts = tag, []
        if tag == "a" and attrs.get("href", "").startswith("https://"):
            self.external_link = attrs["href"]

    def handle_data(self, data):
        if self.inside and not self.skip and self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "nav":
            self.skip -= 1
            return
        if not self.inside or self.skip:
            return
        if tag == "a" and self.external_link:
            self.parts.append(" (" + self.external_link + ")")
            self.external_link = None
        if tag == self.capture:
            content = " ".join("".join(self.parts).split())
            if tag in ("td", "th"):
                self.row.append(content)
            else:
                if tag == "li":
                    self.lists[-1][1] += 1
                    content = (f"{self.lists[-1][1]}. " if self.lists[-1][0] == "ol" else "• ") + content
                self.blocks.append((tag, content))
            self.capture = None
            self.parts = []
        if tag == "tr":
            self.rows.append(self.row)
            self.row = None
        if tag == "table":
            self.blocks.append(("table", self.rows))
            self.rows = None
        if tag in ("ol", "ul"):
            self.lists.pop()
        if tag == "main":
            self.inside = False


def paragraph(parent, text, style=None, bold=False):
    p = word("p", parent)
    if style:
        properties = word("pPr", p)
        word("pStyle", properties, val=style)
    run = word("r", p)
    if bold:
        word("b", word("rPr", run))
    item = word("t", run, text=text)
    item.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


def create_docx(source, destination):
    parser = ManualParser()
    parser.feed(source.read_text(encoding="utf-8"))
    document = word("document")
    body = word("body", document)
    for kind, content in parser.blocks:
        if kind == "page":
            word("br", word("r", word("p", body)), type="page")
        elif kind == "table":
            table = word("tbl", body)
            properties = word("tblPr", table)
            word("tblW", properties, w=9600, type="dxa")
            borders = word("tblBorders", properties)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                word(edge, borders, val="single", sz=4, color="CBD5DF")
            columns = max(len(row) for row in content)
            grid = word("tblGrid", table)
            for _ in range(columns):
                word("gridCol", grid, w=9600 // columns)
            for index, row in enumerate(content):
                tr = word("tr", table)
                row_properties = word("trPr", tr)
                word("cantSplit", row_properties)
                if index == 0:
                    word("tblHeader", row_properties)
                for value in row:
                    cell = word("tc", tr)
                    cell_properties = word("tcPr", cell)
                    word("tcW", cell_properties, w=9600 // columns, type="dxa")
                    if index == 0:
                        word("shd", cell_properties, fill="EAF0F5")
                    paragraph(cell, value, bold=index == 0)
            paragraph(body, "")
        else:
            paragraph(body, content, {"h1": "Title", "h2": "Heading1", "h3": "Heading2"}.get(kind))
    section = word("sectPr", body)
    word("pgSz", section, w=11906, h=16838)
    word("pgMar", section, top=1020, right=1020, bottom=1020, left=1020, header=500, footer=500)
    styles = word("styles")
    defaults = word("docDefaults", styles)
    run_properties = word("rPr", word("rPrDefault", defaults))
    word("rFonts", run_properties, ascii="Calibri", hAnsi="Calibri")
    word("sz", run_properties, val=22)
    word("spacing", word("pPr", word("pPrDefault", defaults)), after=120)
    for name, label, size in (("Title", "Title", 40), ("Heading1", "heading 1", 30), ("Heading2", "heading 2", 25)):
        style = word("style", styles, type="paragraph", styleId=name)
        word("name", style, val=label)
        properties = word("pPr", style)
        word("keepNext", properties)
        word("spacing", properties, before=260, after=140)
        if name != "Title":
            word("outlineLvl", properties, val=0 if name == "Heading1" else 1)
        formatting = word("rPr", style)
        word("b", formatting)
        word("sz", formatting, val=size)
        word("color", formatting, val="183B56")
    types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    document_rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/styles.xml", ET.tostring(styles, encoding="utf-8", xml_declaration=True))
    return len(parser.blocks)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist", help="Folder containing the built exe and build record.")
    dist = parser.parse_args().dist_dir.resolve()
    executable = dist / "RTM Cobot Studio.exe"
    metadata = json.loads((dist / "UR15WebApp2-build.json").read_text(encoding="utf-8"))
    if sha256(executable) != metadata["sha256"]:
        raise ValueError("The executable does not match its build record. Build it again before packaging.")
    documents = ROOT / "documentation/webapp2"
    for name in ("README_FIRST.txt", "USER_MANUAL.html"):
        shutil.copyfile(documents / name, dist / name)
    blocks = create_docx(documents / "USER_MANUAL.html", dist / "USER_MANUAL.docx")
    defaults = dist / "UR15WebApp2-default-data.zip"
    with tempfile.TemporaryDirectory(prefix="webapp2-release-") as temporary:
        temporary = Path(temporary).resolve()
        data = temporary / "seed/RTM Cobot Studio"
        profile = load_profile(data)
        profile.paths["results_directory"].mkdir(parents=True, exist_ok=True)
        with ZipFile(defaults, "w", ZIP_DEFLATED) as archive:
            for path in sorted(data.rglob("*")):
                archive.write(path, str(Path("RTM Cobot Studio") / path.relative_to(data)))
        with ZipFile(defaults) as archive:
            if archive.testzip():
                raise ValueError("The default-data zip is corrupt.")
            for name in archive.namelist():
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError("Unexpected archive path.")
            archive.extractall(temporary / "verify")
        # Confirm the actual exe accepts the distributed defaults, without motion.
        result = subprocess.run([str(executable), "--check-config", "--data-dir", str(temporary / "verify/RTM Cobot Studio")],
                                cwd=temporary, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise ValueError(f"The exe rejected the distributed defaults:\n{result.stdout}\n{result.stderr}")
    names = ["RTM Cobot Studio.exe", "README_FIRST.txt", "USER_MANUAL.html", "USER_MANUAL.docx",
             "UR15WebApp2-default-data.zip", "UR15WebApp2-build.json"]
    (dist / "SHA256SUMS.txt").write_text("".join(f"{sha256(dist / name)}  {name}\n" for name in names), encoding="utf-8")
    release = dist / "UR15WebApp2-release.zip"
    with ZipFile(release, "w", ZIP_DEFLATED) as archive:
        for name in [*names, "SHA256SUMS.txt"]:
            archive.write(dist / name, name)
    with ZipFile(release) as archive:
        if archive.testzip():
            raise ValueError("The release zip is corrupt.")
    print(f"Release ready: {release}\nManual: {blocks} content blocks; default data accepted by the exe.")


if __name__ == "__main__":
    main()
