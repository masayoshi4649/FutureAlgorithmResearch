"""99の正式成果を公開後に再確認し、100の未実行設計と区別して引き継ぐ。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 正式固定又は合格した検査資料を読む。
    引数: path(Path)はJSONファイル。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 入力、売買、会計と公開資料の不変を確かめる。
    引数: path(Path)は参照ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 局所検証の完了と探索目標の未達を分け、次段へ必要事項を保存する。
    引数: なし。
    返り値: None。99金融を変更せず、100の未測定利益を記載しない。
    """
    fixed_path, publication_path = HERE / '事前固定.json', HERE / 'report/公開結果.json'
    fixed, publication = read(fixed_path), read(publication_path)
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in {**publication['公開SHA256'], **publication['旧成果SHA256']}.items():
        assert digest(ROOT / relative) == expected, relative
    paths = [HERE / relative for relative in (
        'analysis/比較結果.json', 'analysis/説明補足.json',
        'analysis/現在支持源の実建値差と消えた勝負及び新固有親.json',
        'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json',
        'review/3正式レビューの独立原因要旨.json',
        'report/表示の独立検査.json', 'report/根担当の目視確認.json',
        'report/公開後の独立不変確認.json')]
    for path in paths:
        proof = read(path)
        assert proof.get('全合格', proof.get('合格', False)), path.name
    comparison = read(paths[0])
    assert len(comparison['results']) == 34 and comparison['both80'] == []
    next_plan = HERE.parent / 'wave_v100/結果前の設計案.json'
    next_catalog = HERE.parent / 'wave_v100/catalog.py'
    plan = read(next_plan)
    assert plan['予定条件数'] == 34 and plan['売買実装'] == plan['正式新条件売買実行'] == 0
    assert not list((next_plan.parent / 'front/results').glob('*.json'))
    assert not list((next_plan.parent / 'back/results').glob('*.json'))
    result = dict(
        全合格=True,
        段階='99の全34全31再生・独立会計・原因・画面・00095公開が完了。探索目標は未達で継続。',
        公開資料=publication['公開資料'], 固定依存検査数=len(fixed['SHA256']),
        公開検査数=len(publication['公開SHA256']), 旧成果検査数=len(publication['旧成果SHA256']),
        条件数=34, 会計口座数=2108, 商品期間数=544,
        主='L1_C1_A7_X3', 前16参考='A0_X1', 安定性改善の採用=False,
        主の成績=dict(TOPIX='2親1勝1敗、−29,336円、2活動場、29無取引場。',
                       NK225='10親1勝9敗、−96,320円、8活動場すべて赤字、23無取引場。'),
        活動増と安定性='L1_C1_A1_X1でTOPIX黒字12/26へ微増したが最大赤字73,336円へ、日経は−16,736円と最大赤字39,456円へ悪化。',
        具体的原因='TOPIX候補4063.5→判断4079.5→実建値4080で16.5pt不利。局所7.5pt押し/3pt回復が成立しても建値後MFE1.5pt<S4.5。価格時計判断296秒と支持格子295秒は真受信経過ではない。',
        反例='日経候補と同値66660の新規でも−11,552円。価格追いだけで全損失を説明しない。',
        次の仮説='元候補から不利な発注判断価格の上限をなし/0.5W/1W/2Wで比較。L0/L1×A1/A7×X1/X3を残しC1へ固定。実指値の約定上限と混同しない。',
        次段理論主=plan['理論主'], 次段対照=plan['対照'], 次段予定条件数=34,
        次段主の理由=plan['主の理由'], 次段売買実装=0, 次段正式損益=0,
        独立範囲='全2108会計/544期間、新支持59と実2列SHA。最初入口出口/内部20/観測10等は5代表310口座、補助10全行再構築ではない。',
        全31既知=True, 未見確認場数=0, API取得=0, 実注文=0,
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                    paths+[fixed_path, publication_path, next_plan, next_catalog,
                           HERE / 'report/次段の候補価格上限案.json']})
    (HERE / '99正式終端と100候補価格上限の未実行引継ぎ.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 固定依存検査数=result['固定依存検査数'],
                         公開後検査数=result['公開検査数'], 探索目標='未達で継続',
                         次段正式損益=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
