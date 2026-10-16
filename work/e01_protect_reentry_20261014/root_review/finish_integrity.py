"""完成した00108の固定源・金融・公開ファイルとリンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00108_利益保護と二市場の再参加検証'


def main() -> None:
    """
    機能: 完成14源と金融及び公開同バイトを照合し、資料リンクを検査する。
    引数: なし。固定と各ファイルの指紋だけを使用する。
    返り値: None。金融・原入力・実台帳を再生せず証跡へ保存する。
    """
    fixed = json.loads((HERE.parent / 'engine/金融事前固定.json').read_text(encoding='utf-8-sig'))
    for relative, expected in fixed['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    expected_files = {
        HERE.parent / 'engine/finance/結果.json': 'c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f',
        PUBLIC / '利益保護と再参加の全場会計.json': '042dc9572c9187db536fe4760069bba64de73efacb90a2b8e0847a757eae1876',
        PUBLIC / '利益を保護して二市場の新支持で再参加するE01と全セッション損益.html': '194216c6903d57e3cab4578b3a0dbff8f47211efa795cadba1533ee2b8ce81c0',
    }
    for path, expected in expected_files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)

    # ----------------------------------------
    # 入口・原因・共通知見のリンクを、損益再計算なしで点検する。
    bank = ROOT / 'アルゴリズム調査/共通/知見台帳'
    files = [ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html']
    files.extend(PUBLIC.glob('*.md'))
    files.extend(bank.glob('*.md'))
    files.append(ROOT / 'アルゴリズム調査/00109_二市場の逆票返済を外した継続検証/README.md')
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
    proof = dict(全合格=True, 固定源=len(fixed['source_SHA256']), 公開リンク=checked,
                  金融と公開同バイト=True, 共通知見五Markdownのみ=True, 新金融=0, 原入力=0, API=0)
    (HERE / '完成時の指紋とリンク.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
