"""101の正式終端と公開を、未実装102の純数学へ引き継ぐ。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 終端した検査と新しい草案を読む。
    引数: path(Path)。
    返り値: dict。JSON資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 検査結果と未実装の次案を識別する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 101の完了と収益未達、102の残作業を別々に記録する。
    引数: なし。
    返り値: None。金融の再実行、完了目標の偽装、現在API取得は行わない。
    """
    audit = read(HERE / 'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json')
    cause = read(HERE / 'review/根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json')
    geometry = read(HERE / 'review/赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json')
    publication = read(HERE / 'report/公開結果.json')
    analysis = read(HERE / 'analysis/比較結果.json')
    next_work = HERE.parent / 'wave_v102'
    plan = read(next_work / '結果前の設計草案.json')
    mathematics = read(next_work / 'engine_preflight/停止線据置と初期幅余裕の結果前数理.json')
    assert audit['合格'] and cause['全合格'] and geometry['全合格'] and publication['全合格']
    assert audit['検査件数']['口座'] == 1240
    assert not (next_work / 'engine.py').exists() and not (next_work / '事前固定.json').exists()
    assert plan['新売買実装'] == plan['正式新損益'] == 0
    assert mathematics.get('全合格', mathematics.get('合格')) is True
    public = ROOT / publication['公開先']
    page = public / '小さく入り利益で増やす手法と全セッション損益.html'
    assert digest(page) == publication['HTML_SHA256']
    for path in (ROOT / 'README.md', ROOT / 'アルゴリズム調査/README.md', ROOT / 'アルゴリズム調査/index.html'):
        assert public.name in path.read_text(encoding='utf-8')
    sources = [HERE / name for name in ('事前固定.json', '前16参考代表.json',
               'analysis/比較結果.json', 'analysis/説明補足.json',
               'audit/全20全31の増玉注文と親cohort及び全原板会計の独立検算.json',
               'review/根説明補足の親内損失と増玉及び予算超過と最悪場の独立反証.json',
               'review/赤字親の初回利益と追加後停止距離及び予算内反復負けの独立原因.json',
               'report/公開結果.json', 'report/表示の独立検査.json', 'report/根担当の目視確認.json')]
    sources += [next_work / name for name in ('結果前の設計草案.json', '結果前の数理明確化.json',
                'engine_preflight/math.py', 'engine_preflight/停止線据置と初期幅余裕の結果前数理.json')]
    sources.append(page)
    output = dict(全合格=True, 正式101及び公開終端=True, 全20全31=True,
        収益目標達成=False, 両商品金額利益80=analysis['both80'],
        主=analysis['primary'], 参考=analysis['selected'],
        研究101の結論='早い増玉を採用しない。初期数量縮小は損失額削減であり黒字確度改善ではない。',
        研究102の状態='草案20条件と純数理のみ。売買未実装・正式固定前・新損益0。',
        次の順序=['独立原因に基づく設計確定', '余裕幅及び線据置の最小実装と純及び原板前検査',
                  '旧8対照の経済nullと未来不変', '損益前固定、前16、独立参考、後15、全数会計及び原因の再確認'],
        終了扱い='研究目標は未達。次の実装と検証を継続する。',
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in sources},
        API取得=0, 実注文=0)
    target = HERE / '101正式終端と102停止余裕の未実装引継ぎ.json'
    assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('101終端と収益未達、102未実装の次手順を保存しました。', flush=True)


if __name__ == '__main__':
    main()
