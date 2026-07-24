# 브랜드 자산 생성 (한 번 실행해 저장소에 커밋) — og 공유 이미지 + favicon
# 팔레트: claret #7a2a38 / claret-deep #5c1e2a / ivory #fbfaf7 / ink #1b1917 / ink-soft #736c60
from PIL import Image, ImageDraw, ImageFont
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLARET, CLARET_DEEP = (122, 42, 56), (92, 30, 42)
IVORY, INK, INK_SOFT = (251, 250, 247), (27, 25, 23), (115, 108, 96)

SERIF = "C:/Windows/Fonts/batang.ttc"   # 바탕(한국어 명조) — 클래식한 워드마크
SANS = "C:/Windows/Fonts/malgun.ttf"    # 맑은 고딕 — 태그라인


def f(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def center(draw, cx, y, text, font, fill):
    b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (b[2] - b[0]) / 2, y), text, font=font, fill=fill)
    return b[3] - b[1]


def make_og():
    """1200x630 공유 카드 — 아이보리 배경, 클라레 포인트."""
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), IVORY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 12], fill=CLARET)              # 상단 클라레 바
    d.rectangle([0, H - 12, W, H], fill=CLARET)          # 하단 클라레 바
    # 워드마크: "포디엄" + 클라레 점
    wf = f(SERIF, 150)
    word = "포디엄"
    wb = d.textbbox((0, 0), word, font=wf)
    ww = wb[2] - wb[0]
    dot_r = 20
    total = ww + 34 + dot_r * 2
    x0 = (W - total) / 2
    d.text((x0 - wb[0], 205), word, font=wf, fill=INK)
    d.ellipse([x0 + ww + 30, 340, x0 + ww + 30 + dot_r * 2, 340 + dot_r * 2], fill=CLARET)
    # 태그라인
    center(d, W / 2, 400, "클래식 음악인을 위한 공고 집약 플랫폼", f(SANS, 40), INK_SOFT)
    center(d, W / 2, 470, "전국 교향악단·교육청·대학·교회 채용 공고 · 매일 자동 수집", f(SANS, 27), INK_SOFT)
    center(d, W / 2, 545, "clddy.github.io/classic-mule", f(SANS, 24), CLARET)
    img.save(os.path.join(BASE, "og-image.png"))
    print("og-image.png 생성 (1200x630)")


def make_favicon(size, out):
    """클라레 라운드 사각 + 아이보리 '포'."""
    scale = 4
    S = size * scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rad = int(S * 0.22)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=rad, fill=CLARET)
    fs = int(S * 0.62)
    font = f(SERIF, fs)
    b = d.textbbox((0, 0), "포", font=font)
    d.text(((S - (b[2] - b[0])) / 2 - b[0], (S - (b[3] - b[1])) / 2 - b[1]), "포", font=font, fill=IVORY)
    img = img.resize((size, size), Image.LANCZOS)
    img.save(os.path.join(BASE, out))
    print(f"{out} 생성 ({size}x{size})")


if __name__ == "__main__":
    make_og()
    make_favicon(32, "favicon-32.png")
    make_favicon(180, "apple-touch-icon.png")
