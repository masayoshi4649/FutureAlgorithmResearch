"""旧33場の未保存終端枚数を補完せず、完了源のflat検査へ委譲できる範囲を確認する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD = ROOT / 'work/e01_adaptive_price_20261014'


def main() -> None:
    """
    機能: 旧dailyのfinish境界を人工で反証し、旧小会計保証の委譲条件を保存する。
    引数: なし。元市場・旧全曲線・旧cache・旧金融結果は読まない。
    返り値: None。終端数量nullを0へ置き換えない。
    """
    path = OLD / 'engine/daily.py'
    spec = importlib.util.spec_from_file_location('independent_v6_original_daily_flat_contract', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    quotes = dict(seq=np.arange(6, dtype=np.int64), time_s=np.arange(6, dtype=float),
        bid=np.full(6, 99.), ask=np.full(6, 101.), quote_valid=np.ones(6, bool))
    checks = 0
    for side in (1, -1):
        entry = np.asarray([[1., 0., 1., side, 1., 101. if side == 1 else 99., 0., 1.]])
        uids = np.asarray([1], np.int64)
        rejected = False
        try:
            module.reconstruct(('人工', 'TOPIX'), entry, uids, quotes, finish=True)
        except AssertionError:
            rejected = True
        assert rejected
        checks += 1
        partial = module.reconstruct(('人工', 'TOPIX'), entry, uids, quotes, finish=False)
        assert partial['summary']['全会計合格'] is False and partial['uid_accounts'][0]['残枚数'] == 1
        checks += 1
        exit_order = np.asarray([[3., 2., 1., -side, 1., 99. if side == 1 else 101., 1., 0.]])
        complete = module.reconstruct(('人工', 'TOPIX'), np.concatenate((entry, exit_order)),
            np.asarray([1, -1], np.int64), quotes, finish=True)
        assert complete['summary']['全会計合格'] is True
        assert complete['long_qty'][-1] == complete['short_qty'][-1] == complete['reserved_exit_fees'][-1] == 0
        assert complete['uid_accounts'][0]['残枚数'] == 0 and complete['summary']['収支'] == -2082.
        checks += 1
    flat = module.reconstruct(('人工', 'TOPIX'), np.empty((0, 8)), np.empty(0, np.int64), quotes, finish=True)
    assert flat['summary']['全会計合格'] is True and flat['summary']['注文件数'] == 0
    checks += 1
    sources = [path, OLD / 'engine/context.py', OLD / 'engine/exit_policy.py', OLD / 'engine/interface.py',
               OLD / 'engine/runner.py', OLD / 'audit/owned/adaptive_finance_check.py',
               ROOT / 'work/e01_improve_20261014/audit/owned/fak_finance_small_check.py']
    value = dict(全合格=True, 純人工検査=checks,
        source_SHA256={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        SOURCEで確認='finish=Trueは買残/売残/残返済料金の末尾0と全UIDremaining0のassertを通過してから全会計合格=Trueを保存する。',
        完成P1経路='interface.prepared(finish=True)→context.prepare→daily.reconstruct(finish=True)。exit_policy.fixed→daily.apply_policyの実政策再会計もfinish=True。未受理は検証済baseを保持。',
        結果経路='runnerはfresh.summaryを保存し、全会計合格を書換えない。独立小会計rows_checkは全行で全会計合格 is Trueを要求。',
        根から受領した既検証事実=dict(正式結果SHA256='13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944',
            選択='TOPIX E01_ADAPT_G50_ADAPT75_P1 / NK E01_ADAPT_G25_ADAPT100_P1', 各商品33行=66,
            全会計合格True=66, 旧独立監査='八適応条件528会計と旧24引用及び全実親両寄与の独立監査.json',
            source23開始終端一致=True),
        verified_flat_basis=dict(使用可=True, 型='旧完了源と既独立小会計への委譲', 終端数量の直接保存=False,
            unknownを0へ補完=False, 新独立全曲線再確認=False,
            条件='根が照合した同じ結果SHA・選択商品設定33行・全会計合格Trueと、旧source署名の結合を保持する。'),
        推奨表現='終端数量は未保存（null）。旧finish=Trueの残玉0検査を通った保存結果へ委譲し、verified_flat=Trueと別欄に記録する。',
        原市場読取=0, 旧cache読取=0, 旧全曲線読取=0, 旧金融結果本文読取=0, 新金融=0,
        留保='SOURCEと人工だけの確認。旧33を新有効性標本に数えず、旧終端枚数を新しく直接測定したとは呼ばない。')
    output = HERE / '旧三十三場の終端flat保証を数量補完せず委譲するSOURCE確認.json'
    assert not output.exists()
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 純人工検査=checks, verified_flat_basis使用可=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
