"""完成した00110の固定源・金融・公開ファイルとリンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00110_価格票と出来高代理票の入口切り分け'


def main() -> None:
    """
    機能: 完成17源と金融及び公開同バイトを照合し、資料リンクを検査する。
    引数: なし。固定と各ファイルの指紋だけを使用する。
    返り値: None。金融・原入力・実台帳を再生せず証跡へ保存する。
    """
    fixed = json.loads((HERE.parent / 'engine/金融事前固定.json').read_text(encoding='utf-8-sig'))
    for relative, expected in fixed['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    expected_files = {
        HERE.parent / 'engine/finance/結果.json': '9c4ec0cb94e09f27a98c6c9462a5de1cc4b6532e5c447f7fa3fc94202a647000',
        PUBLIC / '入口情報別E01の全場会計.json': '481f58915def42d729963119c0f852767921c369bee94e25852efc6382ca6a7f',
        PUBLIC / '価格票と出来高代理票で入口を切り分けるE01と全セッション損益.html': '7a09eba50544f950d1572880bfe8016dc04c89970e1f573b6995a7a6e7e16353',
    }
    for path, expected in expected_files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)
    assert len(fixed['source_SHA256']) == 17

    # ----------------------------------------
    # 入口・原因・共通知見のリンクを、損益再計算なしで点検する。
    bank = ROOT / 'アルゴリズム調査/共通/知見台帳'
    files = [ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html']
    files.extend(PUBLIC.glob('*.md'))
    files.extend(bank.glob('*.md'))
    files.append(ROOT / 'アルゴリズム調査/00111_少ない価格票で注文価格を追わない検証/README.md')
    checked = 0
    for path in files:
        content = path.read_text(encoding='utf-8-sig')
        targets = re.findall(r'\]\(([^)]+)\)', content) + re.findall(r'href="([^"]+)"', content)
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
