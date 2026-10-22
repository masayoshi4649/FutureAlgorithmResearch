"""保存結果と実装だけから、追加一場の凍結比較元を照合する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def reference(relative: str) -> tuple[dict, dict]:
    """
    機能: 明示した保存結果又は小目録の内容と同一性を記録する。
    引数: relative(str)はプロジェクト相対位置。
    返り値: tuple[dict,dict]は解釈結果と位置・SHA256。原市場や配列は読まない。
    """
    path = ROOT / relative
    payload = path.read_bytes()
    return json.loads(payload.decode('utf-8-sig')), dict(path=relative,
        sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def main() -> None:
    """
    機能: 旧40場の範囲と二家族の実装接続、既知の制約を監査領域へ保存する。
    引数: なし。
    返り値: None。戦略再生・入力生成・原市場読取・登録・共通知見変更は行わない。
    """
    e01, e01_ref = reference('work/stability119_20261017/v6_resume/measurement/少額E01固定二設定の追加七場と全四十場.json')
    dual, dual_ref = reference('work/stability119_20261017/v6_resume/root_owned/少額E01二口座の場末収支合算.json')
    gaps, gaps_ref = reference('work/stability123_20261017/途中利確なしの十九間隔と全四十場.json')
    quotes, quotes_ref = reference('work/stability122_20261017/coverage/所有気配入力目録.json')
    assert e01['全合格'] and gaps['passed'] and dual['全合格']
    assert e01['sessions'] == gaps['sessions'] == quotes['sessions']
    assert len(e01['sessions']) == 40
    assert e01['sessions'][0] == '2026-09-21_Day' and e01['sessions'][-1] == '2026-10-16_Night'
    assert len(gaps['specs']) == 19

    # ----------------------------------------
    # 旧40は再生せず保存値を引用し、新10月19日だけを別の追加結果にする。
    sources = {}
    names = (
        'work/stability119_20261017/v6_resume/adapter_v6.py',
        'work/stability119_20261017/v6_resume/source_v6.py',
        'work/stability119_20261017/v6_resume/run_v6.py',
        'work/stability119_20261017/v6_resume/legacy_runtime.py',
        'work/stability119_20261017/v6_resume/clock_adapter.py',
        'work/stability123_20261017/core123.py',
        'work/stability123_20261017/engine123.py',
        'work/stability123_20261017/catalog123.py',
        'work/stability120_20261017/catalog120.py',
    )
    for name in names:
        sources[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    output = dict(passed=True, old_sessions=e01['sessions'], old_count=40,
        expected_new_session='2026-10-19_Day',
        priority=[
            dict(name='少額E01の商品別固定二設定', reason='過去の比較上、黒字場率と損失制限が相対的に良い。ただし小金額・無取引が多い。',
                actual_config=e01['actual_config'], metrics=e01['metrics'],
                dual_metrics=dual['metrics'], baseline=e01_ref, dual_reference=dual_ref,
                caution='旧33は無訂正保存引用、追加7だけ価格時計高水位資格。40場が同じ資格とは呼ばない。二口座合算は共同MTMや分散の証明ではない。'),
            dict(name='途中利確なしの新規間隔19条件', reason='ユーザー直近の比較を固定対照として延長する。過去19条件は全て合計赤字で、有望と再命名しない。',
                specs=gaps['specs'], baseline=gaps_ref, quote_manifest=quotes_ref,
                caution='途中返済なし、引け直前6分BBO代理。初回幅・間隔と気配幅上限・約定許容を連動させない。日経へTOPIXの固定ptを無断転用しない。'),
        ], sources=sources,
        reuse=dict(e01='v6_resumeのSOURCE隔離と高水位時計表示、元48抽出、元85紙上E01、00106実政策の接続を新所有域へコピーして使用。',
            gaps='core123/engine123を同bytes所有コピーし、settings(TOPIX,2026-10-19_Day)と初回・間隔だけを渡す。既存40は保存行再利用。',
            raw44='E01ではconsumer価格資格表示と未加工元時計を使う出来高票を混同しない。seq同値によるBBO対応を維持。'),
        duplicate_search=dict(scope=['共通知見4分類Markdown','調査方針.md','全調査README.md','正式試行data/trials.json'],
            search='オプション、単語option/options、プット、コール', found=0,
            limitation='未整理私有全域の本文は未走査。全過去に重複なしとは断言しない。'),
        audit_requirements=[
            '新日付の境界と場内期限はカレンダーから計算し、過去日付のepochや配列長を固定しない。',
            '金融前に通常版/高速版、外部期待線、原行と同時計の順序、上下鏡像、費用・UID・残玉・代理終端を人工照合する。',
            '新一場の結果を旧40開発集計とは別欄へ示し、一場で安定性や確率を確立したとしない。',
            '19条件を独立19場と数えず、旧40最良を新場の最良へ入れ替えない。',
            '全注文と全玉から収支を再計算し、利益玉だけの集計や無取引を勝ちへ置換しない。',
            'オプション行の独立受信時計が不明なら、先物clockとの順序を推測しない。時刻不明IV更新をLastTimeに付け直さない。',
        ], original_market_reads=0, numerical_array_reads=0, financial_replays=0,
        API=0, real_orders=0, registry_changes=0, common_knowledge_changes=0)
    path = HERE/'比較元と旧四十場境界及びオプション重複の事前照合.json'
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, path=path.relative_to(ROOT).as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), financial_replays=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
