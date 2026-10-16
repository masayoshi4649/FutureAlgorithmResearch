"""00111の固定源と公開同バイト及び最新導線を確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00111_少ない価格票で注文価格を追わない検証'


def main() -> None:
    """
    機能: 完成17源と金融・公開指紋、資料リンク、共通五MDを確認する。
    引数: なし。固定資料とファイル指紋のみ使用する。
    返り値: None。金融本文を解析せず原入力・台帳・APIを再生しない。
    """
    fixed = json.loads((HERE.parent / 'engine/金融事前固定.json').read_text(encoding='utf-8-sig'))
    for relative, expected in fixed['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    expected_files = {
        HERE.parent / 'engine/finance/結果.json': 'fb23ebf7d0f81c8607cc58eb8c97c628a5a56c406d8db934c441718321f995c6',
        PUBLIC / '価格票の最低数別E01の全場会計.json': 'e543125b8ec2a8f625885aaf912a2f7c441d0a151153fe8d2af0f47a21bc4e27',
        PUBLIC / '少ない価格票で注文価格を追わないE01と全セッション損益.html': '9449d627c2faef048e2be1baf6e318978fb3193589e6b4974ede2eaa60542d3c',
    }
    for path, expected in expected_files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)
    assert len(fixed['source_SHA256']) == 17

    # ----------------------------------------
    # 金融を再計算せず、完成資料と次段準備のリンクだけを確認する。
    bank = ROOT / 'アルゴリズム調査/共通/知見台帳'
    files = [ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html']
    files.extend(PUBLIC.glob('*.md'))
    files.extend(bank.glob('*.md'))
    files.extend((ROOT / 'アルゴリズム調査/00112_元の公開時点と継続中の参加機会の診断').glob('*.md'))
    checked = 0
    for path in files:
        text = path.read_text(encoding='utf-8-sig')
        targets = re.findall(r'\]\(([^)]+)\)', text) + re.findall(r'href="([^"]+)"', text)
        for target in targets:
            if '://' in target or target.startswith(('#', 'mailto:')):
                continue
            target = unquote(target.split('#', 1)[0].split('?', 1)[0])
            if target:
                assert (path.parent / target).exists(), (str(path), target)
                checked += 1
    assert {p.name for p in bank.iterdir()} == {'README.md', '入口.md', '継続.md', '出口.md', '売買の工夫.md'}
    proof = dict(全合格=True, 固定源=17, 公開リンク=checked,
                  金融と公開同バイト=True, 共通知見五Markdownのみ=True, 新金融=0, 原入力=0, API=0)
    (HERE / '完成時の指紋とリンク.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
