"""日中診断画像を公開領域へ複製し、本文の相対リンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil


def main() -> None:
    """
    機能: 完成済み26画像を同一内容で公開し、Markdownの参照先を確認する。
    引数: なし。
    返り値: None。画像指紋とリンク存在検査を作業領域へ保存する。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    public = root/"アルゴリズム調査/00129_チャートと板からの失敗機構再検証"
    destination = public/"画像/日中診断"
    destination.mkdir(parents=True, exist_ok=True)
    images = []
    for image in sorted((here/"images").glob("*.png")):
        target = destination/image.name
        shutil.copy2(image, target)
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
        images.append(dict(path=target.relative_to(root).as_posix(), sha256=digest))
    document = public/"日中の画像と改修診断.md"
    links = []
    for relative in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
        target = (public/relative).resolve()
        assert target.is_file(), str(target)
        assert target.is_relative_to(root.resolve())
        links.append(dict(relative=relative, path=target.relative_to(root).as_posix()))
    proof = dict(passed=True, images=images, links=links, image_count=len(images), link_count=len(links),
                 document_sha256=hashlib.sha256(document.read_bytes()).hexdigest(),
                 financial_replays=0)
    output = here/"公開用画像とリンク確認.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, images=len(images), links=len(links), path=str(output)), ensure_ascii=True))


if __name__ == "__main__":
    main()
