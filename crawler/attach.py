# 첨부파일(PDF/HWP/HWPX) 텍스트 추출 + 이미지 공고문 OCR
import io, os, re, zipfile, zlib

TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")

def ocr_image(data: bytes) -> str:
    """공고문이 이미지로만 게시된 경우 (세종문화회관 등) — 한국어 OCR"""
    try:
        import pytesseract
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = TESSERACT
        os.environ["TESSDATA_PREFIX"] = TESSDATA
        img = Image.open(io.BytesIO(data))
        if img.width < 200 or img.height < 200:
            return ""  # 아이콘/장식 이미지 제외
        # 작은 포스터만 확대 (세로로 긴 공고문 원본은 그대로)
        if img.width < 1200 and img.height < 15000:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        text = pytesseract.image_to_string(img.convert("L"), lang="kor+eng")
        # OCR 특유의 글자 간 공백 제거: "접 수 마 감" → "접수마감", "7 . 13" → "7.13"
        text = re.sub(r"(?<=[가-힣])[ \t](?=[가-힣])", "", text)
        text = re.sub(r"(?<=\d)[ \t]*\.[ \t]*(?=\d)", ".", text)
        text = re.sub(r"(?<=\d)[ \t]*~[ \t]*", "~", text)
        return text
    except Exception:
        return ""

def extract_pdf(data: bytes) -> str:
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:10]:
            out.append(page.extract_text() or "")
    text = "\n".join(out)
    # 텍스트가 빈약하면 스캔 PDF — 페이지를 래스터화해 OCR
    if len(re.sub(r"\s", "", text)) < 1500:
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(io.BytesIO(data))
            for i in range(min(len(doc), 4)):
                pil = doc[i].render(scale=2.2).to_pil()
                buf = io.BytesIO()
                pil.save(buf, format="PNG")
                ocr = ocr_image(buf.getvalue())
                if ocr:
                    text += "\n" + ocr
            doc.close()
        except Exception:
            pass
    return text

def _hwp_bodytext(ole) -> str:
    """BodyText 섹션의 HWPTAG_PARA_TEXT(67) 레코드에서 본문 전체 추출.
    PrvText는 1페이지 미리보기뿐이라 뒤쪽 표(접수기간 등)가 잘린다."""
    out = []
    for entry in ole.listdir():
        if entry[0] != "BodyText":
            continue
        raw = ole.openstream(entry).read()
        try:
            raw = zlib.decompress(raw, -15)
        except zlib.error:
            pass
        i = 0
        n = len(raw)
        while i + 4 <= n:
            hdr = int.from_bytes(raw[i:i + 4], "little")
            tag = hdr & 0x3FF
            size = (hdr >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                if i + 4 > n:
                    break
                size = int.from_bytes(raw[i:i + 4], "little")
                i += 4
            if size < 0 or i + size > n:
                break
            if tag == 67:  # HWPTAG_PARA_TEXT
                t = raw[i:i + size].decode("utf-16-le", errors="ignore")
                out.append(re.sub(r"[\x00-\x1f]", " ", t))
            i += size
    return "\n".join(out)

def _hwp_bindata_images(ole, limit=2):
    """HWP 안에 삽입된 이미지(BinData) 추출 — 스캔 공고문 대응"""
    out = []
    for entry in ole.listdir():
        if entry[0] != "BinData" or len(out) >= limit:
            continue
        raw = ole.openstream(entry).read()
        try:
            raw = zlib.decompress(raw, -15)
        except zlib.error:
            pass
        if raw[:2] == b"\xff\xd8" or raw[:4] == b"\x89PNG" or raw[:2] == b"BM":
            if len(raw) > 30_000:  # 로고 등 소형 제외
                out.append(raw)
    return out

def extract_hwp(data: bytes) -> str:
    """구형 HWP(OLE): PrvText + BodyText 전체. 텍스트가 빈약하면(스캔 공고문) 내부 이미지 OCR."""
    import olefile
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        parts = []
        if ole.exists("PrvText"):
            parts.append(ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore"))
        body = _hwp_bodytext(ole)
        if body:
            parts.append(body)
        text = "\n".join(parts)
        if len(re.sub(r"\s", "", text)) < 1500:
            for img in _hwp_bindata_images(ole):
                ocr = ocr_image(img)
                if ocr:
                    text += "\n" + ocr
        return text
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

def extract_any(filename: str, data: bytes, depth: int = 0) -> str:
    """확장자보다 매직바이트 우선 판별. zip이면 내부 문서(중첩 zip 포함)까지 재귀 추출."""
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
                # 일반 zip — 공고문류 우선, 악보 zip은 뒤로. 중첩 zip은 depth 2까지
                names.sort(key=lambda n: ("악보" in n, z.getinfo(n).file_size))
                out = []
                for n in names[:10]:
                    low = n.lower()
                    if low.endswith((".hwp", ".hwpx", ".pdf")):
                        out.append(extract_any(n, z.read(n), depth + 1))
                    elif low.endswith(".zip") and depth < 2:
                        out.append(extract_any(n, z.read(n), depth + 1))
                    if sum(len(t) for t in out) > 3000:
                        break
                return "\n".join(out)
    except Exception as e:
        return f"[추출실패 {type(e).__name__}: {e}]"
    return ""
