"""正式4金融接頭helperの切断接口だけを、正常sourceとreadonlyの人工で確認する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

import adapter
import finance_artificial as artificial
import financial_prefix as prefix


HERE = Path(__file__).resolve().parent


def readonly(value: object) -> None:
    """
    機能: 正式baseとactivityの配列と同じreadonly資格へ人工を固定する。
    引数: value(object)は辞書・列・配列。
    返り値: None。値や並びは変更しない。
    """
    if isinstance(value, np.ndarray):
        value.flags.writeable = False
    elif isinstance(value, dict):
        for child in value.values():
            readonly(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            readonly(child)


def main() -> None:
    """
    機能: 対称4人工の出口直前接頭で、過去注文・全玉時価・lineageを比較する。
    引数: なし。
    返り値: None。正式金融結果・cache・baseは読まない。
    """
    target = HERE / '4先頭親接頭helperの人工切断とreadonly.json'
    assert not target.exists()
    refs = [Path(__file__), HERE / 'financial_prefix.py', HERE / 'finance_adapter.py', HERE / 'adapter.py', HERE / 'finance_artificial.py']
    beginning = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    checks = []
    for symbol in ('TOPIX', 'NK225'):
        for side in (1, -1):
            account, record, signal, opening = artificial.fixture(symbol)
            artificial.install(account, 'C1', [(330, side)])
            prepared = dict(record=record, signal=signal, reference_open=opening, 人工Python=True)
            readonly(prepared)
            readonly(account)
            full = artificial.finance.play(prepared, account, 'C1')
            length = int(full['orders'][1, 1])
            past_account = prefix.account_prefix(account, 'C1', length)
            past_prepared = prefix.prepared_prefix(prepared, length)
            assert not past_prepared['record']['price'].flags.writeable and past_prepared['record']['price'].flags.c_contiguous
            assert not past_prepared['signal']['grid'].flags.writeable and past_prepared['signal']['grid'].flags.c_contiguous
            copied_signal = artificial.finance.connect(past_account, 'C1', past_prepared['record'], past_prepared['signal'], adapter.reference_config(), opening)[0]
            assert all(copied_signal[name].flags.writeable and copied_signal[name].flags.c_contiguous for name in ('event', 'quality', 'reset'))
            past = artificial.finance.play(past_prepared, past_account, 'C1', finish=False)
            checked = prefix.compare(full, past, length, 1)
            checked.update(商品=symbol, 方向=side, 旧価格と旧格子readonly=True, raw新copy可書込=True)
            checks.append(checked)
    ending = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in refs}
    assert beginning == ending
    proof = dict(全合格=True, 人工専用=True, 検査件数=dict(商品方向=4, 出口直前接頭=4, readonly及びcontiguous資格=4),
        検査=checks, 開始終端source一致=True, 開始SHA256=beginning, SHA256=ending,
        正式金融結果読取=0, 正式全32再実行=0, 新counterfactual損益=0, base読取=0, API取得=0)
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 検査件数=proof['検査件数'], 証跡SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
