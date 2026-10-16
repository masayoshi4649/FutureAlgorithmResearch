"""条件別診断の公開MDと限定集計だけを一度読み、文書整合監査用に保全する。"""

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
MD = ROOT / 'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測/S03の値幅と方向の条件別診断.md'
SMALL = ROOT / 'work/topix10pt_20261016/s03_context/S03既158予兆の四分類と因果二対照の集計.json'


def main() -> None:
    """
    機能: 根の許可した2文書を指定SHAで一読保全し、限定schemaを表示する。
    引数: CLIの--md-sha(str)、--small-sha(str)。
    返り値: None。原入力・prepared・金融・HTML・公開JSONは読まない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--md-sha', required=True)
    parser.add_argument('--small-sha', required=True)
    args = parser.parse_args()
    copied = HERE / 'copies'
    assert not copied.exists()
    copied.mkdir()
    reads = []
    for path, expected in ((MD, args.md_sha), (SMALL, args.small_sha)):
        payload = path.read_bytes()
        assert len(payload) < 1024 * 1024
        digest = hashlib.sha256(payload).hexdigest()
        assert digest == expected
        (copied / path.name).write_bytes(payload)
        reads.append(dict(path=path.relative_to(ROOT).as_posix(), SHA256=digest, bytes=len(payload), reads=1))
    md = (copied / MD.name).read_text(encoding='utf-8')
    small = json.loads((copied / SMALL.name).read_text(encoding='utf-8'))
    print(md)
    print(json.dumps(dict(限定集計topkeys=list(small), 型={key:type(value).__name__ for key,value in small.items()}), ensure_ascii=False, indent=2))
    (HERE / '文書監査の二資料一読保全.json').write_text(json.dumps(dict(全合格=True, 目的='新政策成績と混同しない文書整合', reads=reads,
        HTML=0, 公開採点JSON=0, 凍結10source=0, 原入力=0, prepared=0, 金融=0, API=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
