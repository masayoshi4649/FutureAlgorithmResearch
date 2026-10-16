"""実入力の意味別接頭と最初の実追加だけを、元不合格の限界を残して結合する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def digest(path: Path) -> str:
    """
    機能: 現在の読取資料をSHA256で固定する。
    引数: path(Path)は既存資料。
    返り値: str。指紋。売買本体又は原板を再生しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 新たな14接頭の独立19列と未来源比較だけを合格証跡として結ぶ。
    引数: なし。意味別12接頭と実追加2接頭の終端合格JSONが必要。
    返り値: None。原False/原source/元計画を保持し、未記録の48件を足さない。
    """
    target = HERE / '実入力因果不変の補完.json'
    assert not target.exists(), '補完根拠を上書きしません。'
    failed = HERE / '実接頭不合格_00001.json'
    original_source = HERE / '実接頭不合格時点のprefix_00001.py'
    original_plan = HERE / '実接頭検査の結果前計画.json'
    fixed_reach = HERE / '固定二場の主の部分接頭における待機と実追加のカバー診断.json'
    fixed_plan = HERE / '実追加未到達後の固定二場主の補完計画.json'
    fixed_pass = HERE / '固定二場主の待機初回fillと余裕拒否の独立19列及び未来源補完.json'
    added_plan = HERE / '追加固定0930Nightの主だけの結果前カバー計画.json'
    added_reach = HERE / '追加固定0930Nightの主の待機と実追加カバー診断.json'
    added_prefix_plan = HERE / '追加固定0930Nightの最初の実追加接頭計画.json'
    added_pass = HERE / '追加固定0930Nightの主の実追加接頭と独立19列及び未来源不変.json'
    broken = json.loads(failed.read_text(encoding='utf-8'))
    assert broken['全合格'] is False
    assert broken['元の不合格sourceSHA256'] == digest(original_source)
    a = json.loads(fixed_pass.read_text(encoding='utf-8'))
    b = json.loads(added_pass.read_text(encoding='utf-8'))
    for proof, number in ((a, 12), (b, 2)):
        assert proof['全合格'] is True and proof['開始と終端の全依存SHA一致'] is True
        assert proof['検査件数']['接頭'] == proof['検査件数']['独立oracle'] == number
        assert proof['検査件数']['独立gate列'] == 19
        for counter in ('自己LP未来', '相手LP未来', '自己LP同clock後続', '相手LP同clock後続', '自己BBO未来', '相手BBO未公開'):
            assert proof['検査件数'][counter] == number
        assert proof['完結した102口座'] == proof['正式102損益実行'] == proof['API取得'] == proof['実注文'] == 0
        assert proof['開始SHA256'] == proof['SHA256']
        for relative, expected in proof['SHA256'].items():
            assert digest(ROOT / relative) == expected, relative
    assert a['検査件数']['実追加を含む接頭'] == 0 and b['検査件数']['実追加を含む接頭'] == 2
    refs = [Path(__file__), failed, original_source, original_plan, fixed_reach, fixed_plan, fixed_pass,
            added_plan, added_reach, added_prefix_plan, added_pass,
            HERE / '初回coverage補助のpackage名衝突.py', HERE / 'カバー診断初回の外部package名衝突.json',
            HERE / 'reachability.py', HERE / 'night_reachability.py', HERE / 'supplement.py', HERE / 'night_supplement.py']
    financial = [WORK / (name + '.py') for name in ('engine', 'strategy', 'catalog', 'data', 'accounting', 'research')]
    refs += financial
    proof = dict(全合格=True, 合格の対象='新しく詳細保存した主B1_T0の意味別12接頭と最初の実追加2接頭だけ。元不合格の48予定接頭は認定件数へ足さない。',
        主='B1_T0_Q1_X1', 検査件数=dict(新認定接頭=14, 独立gate列=19,
            意味別固定二場の接頭=12, 追加固定一場の実追加接頭=2, 各未来源改変=14,
            独立gate行=a['検査件数']['独立gate行'] + b['検査件数']['独立gate行']),
        固定場=['2026-09-22_Day', '2026-10-08_Night', '2026-09-30_Night'],
        初回の一致根拠='実行出力に固定四代表×固定二場×両商品の16群について一致した旨がある。ただし原失敗JSONには詳細件数/検査例がないため、予定48件を検証済み件数へ推測して足さない。',
        初回不合格の保持='原Falseと当時source及び元計画はそのまま保持。最後の主実追加カバー不足でterminal1。後の診断で元二場は場末10分前まで主追加0と確認。',
        診断と追加場='主の元二場の待機・初fill・余裕拒否を補完。旧101で同入口の実追加原因を確認済みだった09/30Nightをrootが別計画で固定し、両商品で最初の実追加だけを補完。新収益額又は新最大順行を選定へ使わない。',
        範囲='別19gate全行全列は独立Fraction比較。旧70/74/実cohort25/完了親24と旧経済/支持59/入口cap20/21は因果接頭と6未來源改変で比較。',
        限界='真受信順、全特徴の原本からの再生成、全31場全追加fillの未来不変は認定しない。新認定14接頭の条件は主B1_T0だけ。初回他3代表の元ログ一致を詳細認定へ代用しない。人工80の実追加カバーと実データ2接頭の追加カバーを区別する。',
        現在金融本体SHA256={str(path.relative_to(ROOT)): digest(path) for path in financial},
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in refs},
        売買本体変更=0, 原板再生の追加=0, 正式102損益実行=0, API取得=0, 実注文=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(target.read_text(encoding='utf-8')) == proof
    print(json.dumps(dict(全合格=True, 新認定接頭=14, 実追加接頭=2, 証跡SHA256=digest(target)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
