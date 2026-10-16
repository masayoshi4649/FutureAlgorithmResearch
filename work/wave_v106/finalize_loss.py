"""実画像を目視した損失停止四比較の表示と最新導線を確定する。"""

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from finalize_sizing import Links


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def main() -> None:
    """
    機能: rootの三画像目視を記録し、追加12条件後の導線と資料指紋を確定する。
    引数: なし。rootが1450/520と両停止線・旧勝ち喪失の実画像を見た後だけ実行する。
    返り値: None。金融・板・台帳・APIを再生しない。
    """
    proof_path = HERE/'loss_anchor_review/損失停止修正の全場と広狭表示確認.json'
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全合格'] and len(proof['画面']) == 3
    for screen in proof['画面']:
        assert screen['全合格'] and screen['円枚数照合'] == 1360 and screen['概要照合'] == 88
        assert screen['旧勝ち例照合'] == 80 and Path(screen['画像']).is_file()
    proof['根目視確認'] = True
    proof['根目視内容'] = '暗色の広狭画面で本文と横スクロール表が読めること、同母旧比較・初回q比例の両停止線・不変数量予算・失った旧勝ちの展開画面を確認。'
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    # ----------------------------------------
    # 完成金融は変更せず、今回の文書と画面だけを別の証跡に結ぶ。
    targets = [ROOT/'README.md', ROOT/'アルゴリズム調査/README.md', ROOT/'アルゴリズム調査/index.html',
        ROOT/'アルゴリズム調査/調査方針.md', PUBLIC/'README.md',
        PUBLIC/'枚数に合わせた損失停止の修正と全セッション損益.html',
        PUBLIC/'枚数に合わせた利確修正と全セッション損益.html',
        PUBLIC/'損失停止を狭めて失った回復勝ちの具体例.md']
    targets.extend((ROOT/'アルゴリズム調査/共通/知見台帳').glob('*.md'))
    references, shas = [], {}
    for source in targets:
        raw = source.read_bytes(); text = raw.decode('utf-8-sig')
        shas[source.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
        if source.suffix == '.html':
            parser = Links(); parser.feed(text); links = parser.references
        else:
            links = re.findall(r'\]\(([^)]+)\)', text)
        for link in links:
            link = link.strip().strip('<>')
            if not link or link.startswith(('https:', 'http:', 'mailto:', '#')):
                continue
            relative = unquote(link.split('#', 1)[0].split('?', 1)[0])
            assert (source.parent/relative).resolve().is_file(), (source, link)
            references.append(dict(出典=source.relative_to(ROOT).as_posix(), 参照先=link))
    result = dict(全合格=True, 参照確認数=len(references), 対象SHA256=shas,
        根目視資料=proof_path.relative_to(ROOT).as_posix(), 参照=references,
        主評価条件数=369, 今回追加金融条件=4, 目標変更後追加条件=12, 両商品最新三基準合格=0,
        追加金融=0, 原板=0, NPZ=0, API=0)
    destination = HERE/'loss_anchor_review/損失停止修正の目視と最新導線確認.json'
    assert not destination.exists(), '確定証跡は自動で上書きしない'
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(dict(全合格=True, 目視画像=3, 参照確認数=len(references), 両商品三基準合格=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
