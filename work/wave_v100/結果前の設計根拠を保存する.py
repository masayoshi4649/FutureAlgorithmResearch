"""99の正式結論と100の結果前設計を変更せず、参照指紋を別に保存する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main() -> None:
    """
    機能: 結果前の有限設計と前段の正式原因資料の同一性を保存する。
    引数: なし。
    返り値: None。設計案や過去の凍結資料は上書きしない。
    """
    target = HERE / '結果前の設計根拠.json'
    assert not target.exists() and not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    paths = [HERE / 'catalog.py', HERE / '結果前の設計案.json', Path(__file__),
             HERE.parent / 'wave_v99/事前固定.json',
             HERE.parent / 'wave_v99/99正式終端と100候補価格上限の未実行引継ぎ.json',
             HERE.parent / 'wave_v99/review/3正式レビューの独立原因要旨.json',
             HERE.parent / 'wave_v99/analysis/現在支持源の実建値差と消えた勝負及び新固有親.json']
    fingerprints = {}
    for path in paths:
        with path.open('rb') as stream:
            fingerprints[str(path.relative_to(ROOT))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    plan = json.loads((HERE / '結果前の設計案.json').read_text(encoding='utf-8'))
    assert plan['理論主'] == 'P1_L1_C1_A1_X1' and plan['予定条件数'] == 34
    assert plan['正式新条件売買実行'] == plan['現在API取得'] == plan['実注文'] == 0
    value = dict(全合格=True, 新正式損益未実行=True, 主=plan['理論主'],
                 設計根拠SHA256=fingerprints,
                 状態説明='設計案の売買実装0は設計作成時点の履歴。別途事前検査と正式固定が実装後の状態を証明する。')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('100の設計根拠を新正式損益前に保存しました。', flush=True)


if __name__ == '__main__':
    main()
