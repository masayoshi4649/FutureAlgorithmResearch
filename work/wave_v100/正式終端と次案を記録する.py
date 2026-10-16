"""正式100の不変証跡と、未実装101の設計を分けて引き継ぐ。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NEXT = ROOT / 'work' / 'wave_v101'


def read_json(path: Path) -> dict:
    """
    機能: UTF-8のJSON証跡を読み込む。
    引数: path (Path)。読み込み対象の既存ファイル。
    返り値: dict。証跡の内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: ファイル内容のSHA256を計算する。
    引数: path (Path)。既存ファイル。
    返り値: str。16進数のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_hashes(values: dict) -> int:
    """
    機能: 保存済み指紋と現在ファイルを全件照合する。
    引数: values (dict[str, str])。ルート相対パスと期待SHA256。
    返り値: int。一致を確認した件数。不一致は例外で停止する。
    """
    for name, expected in values.items():
        assert digest(ROOT / name) == expected, f'指紋不一致: {name}'
    return len(values)


# ----------------------------------------


def main() -> None:
    """
    機能: 新しい損益を計算せず、100の終了と101の未実装を記録する。
    引数: なし。
    返り値: None。独立反証を含む引継ぎJSONを保存する。
    """
    fixed_path = HERE / '事前固定.json'
    fixed = read_json(fixed_path)
    assert digest(fixed_path) == '4328058a3307a7ff2d18a9480666a3c0a8757889f9a268f5cf84ef4acce0562a'
    assert verify_hashes(fixed['SHA256']) == 1159

    published = read_json(HERE / 'report' / '公開結果.json')
    assert published['全合格']
    assert verify_hashes(published['公開SHA256']) == 6
    assert verify_hashes(published['旧成果SHA256']) == 21

    post_path = HERE / 'report' / '公開後の独立不変確認.json'
    assert digest(post_path) == 'a7fa484bd9fa308c7f078abf928a0cc40d393c236d69e7892032822704008e9f'
    post = read_json(post_path)
    assert post['全合格'] and post['正式会計不変']
    verify_hashes(post['SHA256'])

    comparison = read_json(HERE / 'analysis' / '比較結果.json')
    assert comparison['全合格'] and comparison['条件数'] == 34
    assert len(comparison['sessions']) == 31
    assert comparison['primary'] == 'P1_L1_C1_A1_X1'
    assert comparison['selected'] == 'A0_X1'
    assert not comparison['活動充足の両80']
    assert not comparison['両商品で全場黒字']

    finite = read_json(NEXT / '有限案の純条件確認.json')
    assert finite['全合格'] and finite['条件数'] == 20
    verify_hashes(finite['SHA256'])
    plan = read_json(NEXT / '結果前の設計案.json')
    assert plan['売買実装'] == plan['正式新条件売買実行'] == 0
    assert plan['理論主'] == 'G1_Q1_X1'
    assert not (NEXT / 'engine.py').exists()
    assert not (NEXT / 'analysis' / '比較結果.json').exists()

    critique_path = NEXT / 'review_pre' / '20条件の予算固定増玉と費用及び予約競合の損益前独立反証.json'
    critique = read_json(critique_path)
    assert critique['純数理全合格']
    verify_hashes(critique['SHA256'])

    paths = [fixed_path, post_path, HERE / 'report' / '公開結果.json',
             HERE / 'analysis' / '比較結果.json', HERE / 'analysis' / '説明補足.json',
             HERE / 'audit' / '全34全31の台帳会計と代表待機及び全原板の独立検算.json',
             HERE / 'review' / '3正式レビューの独立原因要旨.json',
             NEXT / '結果前の設計案.json', NEXT / '初版の結果前設計案.json',
             NEXT / 'catalog.py', NEXT / '有限案だけを検算する.py',
             NEXT / '有限案の純条件確認.json', critique_path, Path(__file__)]
    record = {
        '全合格': True,
        '段階': '100の全34全31再生・独立会計・原因・画面・00096公開が完了。探索目標は未達で継続。',
        '公開資料': published['公開資料'],
        '固定依存検査数': 1159, '公開検査数': 6, '旧成果検査数': 21,
        '条件数': 34, '会計口座数': 2108, '商品期間数': 544,
        '主': comparison['primary'], '前16参考': comparison['selected'],
        '安定性改善の採用': False,
        '主の成績': {
            'TOPIX': '収支+245,940円。黒字12/26活動場、最大赤字73,336円。金額利益57.16%。',
            'NK225': '収支−16,736円。黒字10/25活動場、最大赤字39,456円。金額利益48.51%。'},
        '価格制限の効果': '主の最大赤字・活動黒字率は無制限と同じ。日経1取引は入口10pt改善と返済10pt悪化が相殺。注文経路は同一ではない。',
        '具体的原因': '主の最悪3赤字場ではTOPIX赤字5親中3、日経7親中6が保有中に手数料後黒字へ一度も届かない。残るTOPIX2・日経1は途中利益を返した。事後分類を入口判定に使わない。',
        '次の仮説': '初回は両商品とも絶対1/2/4枚。実保有玉の順行利益が追加後の費用と停止余裕を支える時だけ増玉し、初回の金額損失予算は広げない。固定小枚数と旧全量を対照にする。',
        '次段理論主': plan['理論主'], '次段対照': plan['対照'],
        '次段数量縮小対照': plan['数量縮小対照'], '次段予定条件数': 20,
        '次段の検証段階': '有限条件と純数理反証のみ。売買実装・新正式損益は未実行。',
        '次段仕様確定合格': critique['仕様確定合格'],
        '次段独立判定': critique['判定'],
        '次段売買実装': 0, '次段正式損益': 0,
        '評価優先': '最大収益より赤字頻度・平均最大赤字・下方偏差・大勝ち除外収支を優先。無取引は勝ちとしない。',
        '全31既知': True, '未見確認場数': 0, 'API取得': 0, '実注文': 0,
        '探索目標達成': False,
        '根拠SHA256': {str(path.relative_to(ROOT)): digest(path) for path in paths},
    }
    output = HERE / '100正式終端と101初回配分の未実行引継ぎ.json'
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('100の正式終端を確認。101は20条件の未実装案。目標未達で継続。', flush=True)


if __name__ == '__main__':
    main()
