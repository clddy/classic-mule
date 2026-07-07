# 첨부파일(PDF/HWP/HWPX) 텍스트 추출
import io, re, zipfile, zlib

def extract_pdf(data: bytes) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:10]:
            out.append(page.extract_text() or "")
    return "\n".join(out)

def extract_hwp(data: bytes) -> str:
    """구형 HWP(OLE): PrvText 스트림(UTF-16 미리보기)이 가장 안정적"""
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        if ole.exists("PrvText"):
            raw = ole.openstream("PrvText").read()
            return raw.decode("utf-16-le", errors="ignore")
        # PrvText가 없으면 BodyText 섹션 압축 해제 (best effort)
        out = []
        for entry in ole.listdir():
            if entry[0] == "BodyText":
                raw = ole.openstream(entry).read()
                try:
                    raw = zlib.decompress(raw, -15)
                except zlib.error:
                    pass
                # HWP 레코드에서 한글 텍스트만 대충 건짐
                text = raw.decode("utf-16-le", errors="ignore")
                out.append(re.sub(r"[^가-힣㄰-㆏\w\s.,()~\-:/·]", " ", text))
        return "\n".join(out)
    finally:
        ole.close()

def extract_hwpx(data: bytes) -> str:
    """신형 HWPX: zip 안의 XML에서 텍스트 추출"""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.startswith("Contents/section")]
        if not names and "Preview/PrvText.txt" in z.namelist():
            return z.read("Preview/PrvText.txt").decode("utf-8", errors="ignore")
        for n in sorted(names):
            xml = z.read(n).decode("utf-8", errors="ignore")
            out.append(re.sub(r"<[^>]+>", " ", xml))
    return "\n".join(out)

def extract_any(filename: str, data: bytes) -> str:
    """확장자보다 매직바이트 우선 판별. zip이면 내부의 hwp/pdf까지 재귀 추출."""
    fn = (filename or "").lower()
    try:
        if data[:5] == b"%PDF-" or fn.endswith(".pdf"):
            return extract_pdf(data)
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or fn.endswith(".hwp"):
            return extract_hwp(data)
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                if any(n.startswith("Contents/section") or n == "Preview/PrvText.txt" for n in names):
                    return extract_hwpx(data)
                # 일반 zip — 내부 문서들 재귀 추출 (성남 등 첨부 일괄 zip 대응)
                out = []
                for n in names[:10]:
                    if n.lower().endswith((".hwp", ".hwpx", ".pdf")):
                        out.append(extract_any(n, z.read(n)))
                return "\n".join(out)
    except Exception as e:
        return f"[추출실패 {type(e).__name__}: {e}]"
    return ""
