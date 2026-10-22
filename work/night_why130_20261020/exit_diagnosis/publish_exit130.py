"""出口診断画像を公開領域へ複写し、指紋と文書リンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil


def main() -> None:
    """
    機能: 作成済み画像10枚を公開診断へ複写し、リンクの存在を照合する。
    引数: なし。
    返り値: None。数値源・過去資料を変更せず、公開画像と確認JSONを保存する。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    public = root/"アルゴリズム調査/00130_夜間損失のなぜ三段階と再改善"
    destination = public/"画像/出口診断"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((here/"出口診断の画像と表示範囲.json").read_text(encoding="utf-8"))
    copied = []
    for item in manifest["images"]:
        source = root/item["path"]
        target = destination/source.name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
        shutil.copyfile(source, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]
        copied.append(dict(path=target.relative_to(root).as_posix(), sha256=item["sha256"]))
    document = public/"出口と途中判断のなぜ三段階.md"
    links = re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8"))
    for link in links:
        assert (document.parent/link).resolve().exists(), link
    proof = dict(images=copied, links=links, passed=True,
        viewed_scope="5経路それぞれ新規約定までと旧返済後までの10画像を視認。図の表示調整後も新規までの軸は接頭資料のみ。",
        financial_replays=0, API=0,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (here/"公開画像の指紋とリンク確認.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=True, images=len(copied), links=len(links)), ensure_ascii=False))


if __name__ == "__main__":
    main()
