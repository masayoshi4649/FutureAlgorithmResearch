"""全方法シートの見出し・固有説明・総計を、目視確認用の一覧画像へ並べる。"""

from pathlib import Path
from PIL import Image


HERE = Path(__file__).resolve().parent.parent / "xlsx_checks"


def main():
    """既存の全シート描画から確認画像だけを作る。

    引数: なし。
    返り値: None。XLSXや原データは変更しない。
    """
    paths = sorted(HERE.glob("日経_*.png"))
    for page in range((len(paths) + 7) // 8):
        frames = []
        for path in paths[page * 8:(page + 1) * 8]:
            source = Image.open(path).convert("RGB")
            header = source.crop((0, 20, source.width, 230))
            total = source.crop((0, source.height - 36, source.width, source.height))
            frame = Image.new("RGB", (source.width, header.height + total.height + 10), "#eef2f7")
            frame.paste(header, (0, 0))
            frame.paste(total, (0, header.height))
            frames.append(frame)
        contact = Image.new("RGB", (max(frame.width for frame in frames), sum(frame.height for frame in frames)), "white")
        y = 0
        for frame in frames:
            contact.paste(frame, (0, y))
            y += frame.height
        contact.save(HERE / f"方法別の目視確認_{page + 1}.png")


if __name__ == "__main__":
    main()
