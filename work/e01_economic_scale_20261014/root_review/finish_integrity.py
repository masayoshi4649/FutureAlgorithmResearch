"""完成した00107の金融指紋と公開入口を、金融再生なしで点検する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00107_保有容量と一取引利益の再検証'


def main() -> None:
    """
    機能: 正式源・結果・公開関連リンクを確認し、完成証拠を保存する。
    引数: なし。固定JSONは源指紋の検査だけに使用する。
    返り値: None。新しい金融入力を読まず、既金融を運転しない。
    """
    fixed = json.loads((HERE.parent / 'engine/金融事前固定.json').read_text(encoding='utf-8-sig'))
    for relative, expected in fixed['source_SHA256'].items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, relative
    finance = HERE.parent / 'engine/finance/結果.json'
    assert hashlib.sha256(finance.read_bytes()).hexdigest() == 'ae42bdd2d82470eba5e7791dbc1bdc57761a9be6b7adf68934fbd7d444227e99'

    # ----------------------------------------
    # 公開の入口と知見のリンク先を、内容の再計算なしで確認する。
    files = [ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md',
             ROOT / 'アルゴリズム調査/index.html',
             ROOT / 'work/e01_protect_reentry_20261014/調査意図.md']
    files.extend(PUBLIC.glob('*.md'))
    files.extend((ROOT / 'アルゴリズム調査/共通/知見台帳').glob('*.md'))
    checked = 0
    for path in files:
        content = path.read_text(encoding='utf-8-sig')
        targets = re.findall(r'\]\(([^)]+)\)', content)
        targets.extend(re.findall(r'href="([^"]+)"', content))
        for target in targets:
            if '://' in target or target.startswith(('#', 'mailto:')):
                continue
            target = unquote(target.split('#', 1)[0].split('?', 1)[0])
            if not target:
                continue
            assert (path.parent / target).exists(), (str(path), target)
            checked += 1
    bank = ROOT / 'アルゴリズム調査/共通/知見台帳'
    assert {p.name for p in bank.iterdir()} == {'README.md', '入口.md', '継続.md', '出口.md', '売買の工夫.md'}
    result = dict(全合格=True, 固定源=len(fixed['source_SHA256']), 公開リンク=checked,
                  金融結果不変=True, 共通知見五Markdownのみ=True, 新金融=0, API=0)
    (HERE / '完成時の金融指紋と公開リンク.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
