"""少数開始と順行追加の保存台帳を、注文・使用枠・料金込み床から独立照合する。"""

import argparse
import hashlib
import pickle
import sys
import numpy as np
from diagnose import ROOT, HERE, read, save
from boundaries import module

ROUND = ROOT / 'work/wave_v87/round6'


def digest(path):
    """
    機能: 固定ソースと保存結果の指紋を取得する。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quantity_rules(ready, ledger, config, strategy, checks, account, traced):
    """
    機能: 初回数量、次観測の追加、静観禁止、共有枠と実料金の床を確認する。
    引数: ready/ledger/config/traced(dict)、strategy/checks/account(module)。
    返り値: dict[str,int]。保存注文を変更せず新たな売買判断も行わない。
    """
    orders = ledger['orders']
    entries = orders[orders[:, 7] == 1]
    initial = config['initial_top'] * (1 if ready['symbol'] == 'TOPIX' else 2)
    quiet = strategy.prior.old.old.time_filter.features(ready, 'U')
    seen = set()
    additions = 0
    for order in entries:
        row, source, cid = map(int, order[:3])
        assert source < row
        assert not quiet['active'][row] and not quiet['force'][row]
        if cid not in seen:
            assert order[4] == initial and order[6] != 75
            seen.add(cid)
        else:
            assert order[6] == 75
            matched = ledger['allocation_events']
            matched = matched[(matched[:, 0] == row) & (matched[:, 1] == cid) & (matched[:, 2] == 2)]
            assert len(matched) == 1
            event = matched[0]
            np.testing.assert_array_equal(event[3:7], [source, order[3], order[4], order[5]])
            additions += 1
    # ----------------------------------------
    # 初回準備の照合へ追加注文を混ぜず、静観時の返済量は全在庫で照合する。
    first_only = dict(ledger, orders=orders[~((orders[:, 7] == 1) & (orders[:, 6] == 75))])
    account.time_windows(ready, first_only, traced, strategy.prior.old.old, 'U')
    return dict(追加約定数=additions, 床更新独立復元数=checks.floor_rules(ledger, ready, config),
                共有枠照合数=checks.slot_rules(ledger, ready, config))


def main():
    """
    機能: 十一条件・両約定モデルの全保存口座を独立会計で照合する。
    引数: --partial(bool)は保存済みのみ、--resume(bool)は指紋一致した既確認を再利用する。
    返り値: None。戦略再生や条件選抜は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--partial', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    strategy = module('監査87配分保存戦略', ROUND / 'strategy.py')
    checks = module('監査87配分保存規則', HERE / 'allocation_checks.py')
    folder = ROOT / 'work/wave_v85/audit'
    sys.path.insert(0, str(folder))
    module('original', folder / 'original.py')
    account = module('監査87配分独立会計', folder / 'accounts.py')
    fifo = module('監査87配分独立FIFO', HERE / 'allocation_fifo.py')
    prepare = module('監査87配分保存入力', ROOT / 'work/wave_v85/prepare.py')
    fixed = read(ROUND / '事前固定.json')
    for name, value in fixed['code_SHA256'].items():
        assert digest(ROOT / name) == value, name
    inputs, _, _ = prepare.load_inputs(verify=False)
    reports = []
    totals = dict(口座数=0, 注文数=0, 決済脚数=0, 追加約定数=0, 床更新独立復元数=0, 共有枠照合数=0)
    progress = HERE / '数量配分条件の途中独立会計_会計修正版.json'
    if args.resume and progress.exists():
        prior = read(progress)
        assert prior['全合格']
        reports = prior['条件別']
        totals = {key: prior[key] for key in totals}
    for model in fixed['models']:
        for config in fixed['catalog']:
            path = ROUND / model / 'results' / f"{config['id']}.json"
            if args.partial and not path.exists():
                continue
            packet = read(path)
            ledger_path = ROUND / model / 'ledgers' / f"{config['id']}.pkl"
            assert packet['config'] == config and packet['model'] == model
            assert packet['run']['code_SHA256'] == fixed['code_SHA256']
            assert packet['run']['input_SHA256'] == fixed['input_SHA256']
            assert digest(ledger_path) == packet['ledger_SHA256']
            completed = next((v for v in reports if v['モデル'] == model and v['条件'] == config['id']), None)
            if completed:
                assert digest(path) == completed['結果SHA256'] and digest(ledger_path) == completed['台帳SHA256']
                continue
            ledgers = pickle.loads(ledger_path.read_bytes())
            rows = []
            for actual in packet['rows']:
                key = actual['session'], actual['symbol']
                ready, ledger = inputs[key], ledgers[key]
                old = dict(ledger, config=ledger['settings'], trades=ledger['net_trades'],
                           fees=np.asarray(ledger['fees']).tolist())
                row, _, raw = fifo.measure(ready, old, model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1, 11), ledger['trades'])
                traced = account.trace(ready, ledger, row)
                account.ratios(row)
                account.equal(row, actual)
                verified = quantity_rules(ready, ledger, config, strategy, checks, account, traced)
                for name, value in verified.items():
                    totals[name] += value
                totals['口座数'] += 1
                totals['注文数'] += len(ledger['orders'])
                totals['決済脚数'] += len(ledger['trades'])
                rows.append(row)
            periods = {p: {s: account.aggregate(fifo, rows, s, fixed[p]) for s in ('TOPIX', 'NK225')}
                       for p in ('前16', '後14', '全30')}
            account.equal(periods, packet['periods'])
            reports.append(dict(モデル=model, 条件=config['id'], 結果SHA256=digest(path),
                                台帳SHA256=digest(ledger_path), 全合格=True))
            print(model, config['id'], '会計・共有枠・料金込み床一致', flush=True)
    if not args.partial:
        assert len(reports) == 22 and totals['口座数'] == 1320
    for name, value in fixed['code_SHA256'].items():
        assert digest(ROOT / name) == value, name
    save('数量配分条件の途中独立会計_会計修正版.json' if args.partial else '全11数量条件の独立会計と共有枠と料金床_会計修正版.json',
         dict(全合格=True, 検証作業='round6', 条件数=len(reports), **totals, 条件別=reports, 親会計関数呼出=False,
              監査器SHA256=digest(__import__('pathlib').Path(__file__))))


if __name__ == '__main__':
    main()
