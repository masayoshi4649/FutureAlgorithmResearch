"""98の正式結果と公開資料を不変確認し、次段の未測定仮説を区別して保存する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 正式固定又は検査記録を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 公開後に入力、売買及び会計が変更されていないことを確認する。
    引数: path(Path)は参照資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 局所検証の終了と探索全体の未達を分けて次段へ渡す。
    引数: なし。
    返り値: None。旧損益を変更せず、次段の未測定成績を記載しない。
    """
    fixed_path, publication_path = HERE / '事前固定.json', HERE / 'report/公開結果.json'
    fixed, publication = read(fixed_path), read(publication_path)
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in {**publication['公開SHA256'], **publication['旧成果SHA256']}.items():
        assert digest(ROOT / relative) == expected, relative
    proof_paths = [HERE / relative for relative in (
        'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json',
        'review/3正式レビューと追加門番診断の独立原因要旨.json',
        'analysis/時計政策の実建値差と消えた勝負及び新固有親.json',
        'analysis/説明補足.json', 'report/表示の独立検査.json',
        'report/根担当の目視確認.json', 'report/公開後の独立不変確認.json')]
    for path in proof_paths:
        saved = read(path)
        assert saved.get('全合格', saved.get('合格', False)), path.name
    comparison = read(HERE / 'analysis/比較結果.json')
    assert len(fixed['条件']) == len(comparison['results']) == 34
    assert comparison['both80'] == [] and len(fixed['全31']) == 31
    next_plan = HERE.parent / 'wave_v99/結果前の設計案.json'
    assert read(next_plan)['正式新条件売買実行'] == 0
    assert not list((next_plan.parent / 'front/results').glob('*.json'))
    assert not list((next_plan.parent / 'back/results').glob('*.json'))
    result = dict(
        全合格=True,
        段階='98の正式再生、独立検算、原因調査、画面検査と00094公開が完了。探索目標は未達で継続。',
        公開資料=publication['公開資料'], 固定依存検査数=len(fixed['SHA256']),
        公開後検査数=len(publication['公開SHA256']), 旧成果検査数=len(publication['旧成果SHA256']),
        条件数=34, 全セッション数=31, 商品数=2, 会計口座数=2108,
        主='C1_A7_X3', 参考='A0_X1', 安定性改善の採用=False,
        主の成績=dict(TOPIX='無取引31場、0円。', NK225='5取引5赤字、−56,160円。'),
        部分的な赤字額改善='C1_A1_X1はTOPIX＋247,944円、日経＋34,080円、最大赤字38,004円/26,304円。ただし活動黒字11/26場と9/23場、日経の最大利益日除外は−34,912円。毎場安定とは扱わない。',
        原因='TOPIXの押し回復203保存変化点は2候補。全点で旧の日経300秒mid窓が不明。旧窓不明と実反転は区別する。時計取消を外すと日経の新3敗−33,056円が加わり、共通2取引の建値は変わらなかった。',
        次の仮説='現在方向支持のみ旧mid300窓から既存の独立LP300窓へ替える。候補、硬反対、時計政策、BBO、幾何、出口と数量を保持する。支持列はC3再準備にも作用する。',
        次段理論主=read(next_plan)['理論主'], 次段予定条件数=34,
        次段正式売買結果=0, 次段採用済条件=0,
        独立範囲='全2108会計と544商品期間。最初触発と内部20/観測10等は5代表310口座。補助10フラグの全行独立再構築とは呼ばない。',
        全31既知=True, 未見確認場数=0, 現在API取得=0, 実注文=0,
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in
                    proof_paths+[fixed_path, publication_path, HERE / 'analysis/比較結果.json', next_plan]})
    (HERE / '98正式終端と99現在支持源の未測定引継ぎ.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 固定依存検査数=result['固定依存検査数'],
                         公開後検査数=result['公開後検査数'], 探索目標='未達で継続'), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
