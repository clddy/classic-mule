# 첨부파일(PDF/HWP/HWPX/XLSX) 텍스트 추출 + 이미지 공고문 OCR
import io, os, re, zipfile, zlib, html

TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSDATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tessdata")

OCR_MAX_W = 1800     # Tesseract가 안정적으로 읽는 폭 상한
OCR_TILE_H = 2200    # 세로 조각 높이 (겹침을 둬서 경계에 걸친 줄을 잃지 않는다)
OCR_OVERLAP = 120


def _ocr_tiled(pytesseract, Image, gray):
    """세로로 긴 인포그래픽은 조각내어 읽는다.

    통영시민오케스트라 공고는 4500×13577px 한 장이었는데, 통째로 넘기면 Tesseract가
    전부 뭉개 알아볼 수 없는 기호만 뱉었다(2026-07-29 규명 — 화면에는 '접수기간
    7.20.(월)~8.14.(금)'이 또렷이 보이는데도 마감일을 못 찾았다).
    폭을 적정선으로 줄이고 세로로 잘라 넘기면 정상적으로 읽힌다.
    """
    if gray.width > OCR_MAX_W:      # 폭이 크면 비율 유지하며 축소 (글자가 작아지지 않게 최소한만)
        h = int(gray.height * OCR_MAX_W / gray.width)
        gray = gray.resize((OCR_MAX_W, h), Image.LANCZOS)
    if gray.height <= OCR_TILE_H:
        return pytesseract.image_to_string(gray, lang="kor+eng")
    parts, y = [], 0
    while y < gray.height:
        box = gray.crop((0, y, gray.width, min(y + OCR_TILE_H, gray.height)))
        parts.append(pytesseract.image_to_string(box, lang="kor+eng"))
        y += OCR_TILE_H - OCR_OVERLAP
    return "\n".join(parts)


def ocr_image(data: bytes) -> str:
    """공고문이 이미지로만 게시된 경우 (세종문화회관 등) — 한국어 OCR"""
    try:
        import pytesseract
        from PIL import Image
        # 윈도우 로컬만 명시 경로/tessdata 지정. 리눅스(Actions)는 PATH의 tesseract +
        # apt로 깐 tesseract-ocr-kor(시스템 tessdata)를 그대로 쓴다.
        if os.path.exists(TESSERACT):
            pytesseract.pytesseract.tesseract_cmd = TESSERACT
            os.environ["TESSDATA_PREFIX"] = TESSDATA
        img = Image.open(io.BytesIO(data))
        if img.width < 200 or img.height < 200:
            return ""  # 아이콘/장식 이미지 제외
        # 작은 포스터만 확대 (세로로 긴 공고문 원본은 그대로)
        if img.width < 1200 and img.height < 15000:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        text = _ocr_tiled(pytesseract, Image, img.convert("L"))
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

def extract_xlsx(data: bytes) -> str:
    """XLSX(엑셀): 공유문자열 + 시트 셀을 '행 단위'로 추출. openpyxl 없이 zip+XML 파싱.
    대학 강사 채용의 '채용 교과목 현황'이 xlsx로만 오는 경우(순천대·원광대 등) 대응."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            xml = z.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
            for si in re.findall(r"<si\b[^>]*>(.*?)</si>", xml, re.S):
                shared.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
        out = []
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        for sn in sheets:
            xml = z.read(sn).decode("utf-8", errors="ignore")
            for row in re.findall(r"<row\b[^>]*>(.*?)</row>", xml, re.S):
                cells = []
                for attrs, inner in re.findall(r"<c\b([^>]*)>(.*?)</c>", row, re.S):
                    t = re.search(r'\bt="([^"]+)"', attrs)
                    typ = t.group(1) if t else None
                    if typ == "s":  # 공유문자열 인덱스
                        v = re.search(r"<v>(\d+)</v>", inner)
                        if v and 0 <= int(v.group(1)) < len(shared):
                            cells.append(shared[int(v.group(1))])
                    elif typ == "inlineStr":
                        cells.append(html.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", inner, re.S))))
                    else:  # str/숫자
                        v = re.search(r"<v>(.*?)</v>", inner, re.S)
                        if v:
                            cells.append(html.unescape(v.group(1)))
                if cells:
                    out.append(" | ".join(c for c in cells if c))
    return "\n".join(out)


def extract_any(filename: str, data: bytes, depth: int = 0) -> str:
    """확장자보다 매직바이트 우선 판별. zip이면 내부 문서(중첩 zip 포함)까지 재귀 추출."""
    fn = (filename or "").lower()
    try:
        # 이미지 → OCR. 이 분기가 없어서 본문 <img> 공고를 내려받고도 전부 0자였다 —
        # ocr_image 는 hwp 내부 이미지 경로에서만 쓰이고 extract_any 는 이미지를 그냥
        # 흘려보냈다 (2026-08-11 이미지 백필에서 발각).
        if (data[:2] == b"\xff\xd8" or data[:4] == b"\x89PNG" or data[:2] == b"BM"
                or data[:6] in (b"GIF87a", b"GIF89a")
                or re.search(r"\.(jpe?g|png|gif|bmp)(\.|$)", fn)):
            return ocr_image(data)
        if data[:5] == b"%PDF-" or fn.endswith(".pdf"):
            return extract_pdf(data)
        if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or fn.endswith(".hwp"):
            return extract_hwp(data)
        if fn.endswith((".xlsx", ".xlsm")):
            return extract_xlsx(data)
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = z.namelist()
                nameset = set(names)
                if any(n.startswith("Contents/section") or n == "Preview/PrvText.txt" for n in names):
                    return extract_hwpx(data)
                if "xl/workbook.xml" in nameset:      # 단일 xlsx (매직바이트만 PK)
                    return extract_xlsx(data)
                # 첨부 묶음 zip — 교과목/공고문 우선, 동의서·서식·매뉴얼·악보는 뒤로. 중첩 zip은 depth 2까지
                def _pri(n):
                    boiler = bool(re.search(r"동의서|서식|매뉴얼|맵|계획서|환산|안내|악보", n))
                    subj = bool(re.search(r"교과목|공고|채용|모집|전공|현황|대상", n))
                    return (boiler, not subj, z.getinfo(n).file_size)
                names.sort(key=_pri)
                out = []
                for n in names[:12]:
                    low = n.lower()
                    if low.endswith((".hwp", ".hwpx", ".pdf", ".xlsx", ".xlsm")):
                        out.append(extract_any(n, z.read(n), depth + 1))
                    elif low.endswith(".zip") and depth < 2:
                        out.append(extract_any(n, z.read(n), depth + 1))
                    if sum(len(t) for t in out) > 4000:
                        break
                return "\n".join(out)
    except Exception as e:
        return f"[추출실패 {type(e).__name__}: {e}]"
    return ""
