"""会計と統計は旧版を保ち、同期した短縮影の独立監査へ接続する。"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
_saved=list(sys.path)
sys.path.insert(0,str(HERE.parent/'wave_v38'))
import adaptive_accounting_audit as prior
sys.path[:]=_saved
import integration_slot_audit as slots

cash,statistics=prior.cash,prior.statistics
cash.close=prior.close


def inspect(spec: dict, ready: dict, result: dict, config: dict, columns: tuple) -> tuple:
    """機能: 一入力の注文会計・全行枠・公開予約・表示統計を別式で再構成する。

    引数: spec/ready/result/config (dict)、columns (tuple[ndarray])。
    返り値: 独立指標・独立曲線・枠証跡・基本会計 (tuple)。
    """
    assert len(columns) == 10
    state,bad,bad_source,good,good_source,valid,branch,branch_source,branch_valid,choice = columns
    basic, curves = cash.reconstruct(ready, result, ready['symbol'])
    proof = slots.audit(ready, result, config, spec['policy'], bad, bad_source, good, good_source, valid, curves,
        state=state, budget_enabled=spec['budget_enabled'], min_delay_seconds=spec['min_delay_seconds'],
        observed_fill=spec['observed_fill'], branch_direction=branch, branch_source=branch_source,
        branch_valid=branch_valid, branch_mode=spec['branch_mode'], branch_choice=choice, branch_seed=spec['branch_seed'])
    row = statistics.session(spec['id'], ready, result, config, basic, curves, columns, spec)
    return row, curves, proof, basic


def verify_source() -> None:
    """機能: 会計接続の関数本文が旧版とASTで同じことを確認する。

    引数: なし。返り値: なし(None)。監査呼出先だけを別モジュールで明示する。
    """
    previous=ast.parse(Path(prior.__file__).read_text(encoding='utf-8'))
    current=ast.parse(Path(__file__).read_text(encoding='utf-8'))
    one=next(n for n in previous.body if isinstance(n,ast.FunctionDef) and n.name=='inspect')
    two=next(n for n in current.body if isinstance(n,ast.FunctionDef) and n.name=='inspect')
    assert ast.dump(one,include_attributes=False)==ast.dump(two,include_attributes=False)
    assert Path(prior.__file__).resolve()==HERE.parent/'wave_v38/adaptive_accounting_audit.py'
    assert Path(slots.__file__).resolve()==HERE/'integration_slot_audit.py'


verify_source()
