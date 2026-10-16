"""完成した00109の固定源・金融・公開ファイルとリンクを確認する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00109_二市場の逆票返済を外した継続検証'


def main() -> None:
    """
    機能: 完成16源と金融及び公開同バイトを照合し、資料リンクを検査する。
    引数: なし。固定と各ファイルの指紋だけを使用する。
    返り値: None。金融・原入力・実台帳を再生せず証跡へ保存する。
    """
    fixed = json.loads((HERE.parent / 'engine/金融事前固定.json').read_text(encoding='utf-8-sig'))
    for relative, expected in fixed['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    expected_files = {
        HERE.parent / 'engine/finance/結果.json': '6bc96e20d9ea72af1df51ed73d4595be5cadc1e9ac8760c9a69a1a501cd8886d',
        PUBLIC / '逆票返済OFFの全場会計.json': '60fc23d9f35c30d01f68a3f1d2554c66fee9889e5c73ce86e182b39996c246a3',
        PUBLIC / '二市場の逆票返済を外したE01と全セッション損益.html': '030a5426da870f7733437426b9c46df88cf6cbd137e15632d6fccbee8d8aca9c',
    }
    for path, expected in expected_files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, str(path)
    assert len(fixed['source_SHA256']) == 16

    # ----------------------------------------
    # 入口・原因・共通知見のリンクを、損益再計算なしで点検する。
    bank = ROOT / 'アルゴリズム調査/共通/知見台帳'
    files = [ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html']
    files.extend(PUBLIC.glob('*.md'))
    files.extend(bank.glob('*.md'))
    files.append(ROOT / 'アルゴリズム調査/00110_価格票と出来高代理票の入口切り分け/README.md')
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
    proof = dict(全合格=True, 固定源=16, 公開リンク=checked,
                  金融と公開同バイト=True, 共通知見五Markdownのみ=True, 新金融=0, 原入力=0, API=0)
    (HERE / '完成時の指紋とリンク.json').write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
