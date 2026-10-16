"""固定十二条件の全会計・実際の入口支持・元値換算の証跡を独立照合する。"""

import argparse
import hashlib
import json
import pickle
from pathlib import Path
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[2]
sys.path.insert(0, str(WORK))
import strategy


def read(path):
    """
    機能: 保存JSONを読取専用で開く。
    引数: path (Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    """
    機能: ファイルを分割して指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(8*1024*1024),b''):
            result.update(data)
    return result.hexdigest()


def save(name, value):
    """
    機能: 担当監査フォルダへ有限JSONを安全に確定する。
    引数: name (str)、value (dict)。
    返り値: None。
    """
    target = HERE/name
    assert target.resolve().is_relative_to(HERE)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(target)


def entry_evidence(ready, ledger, config, short):
    """
    機能: 新規の一行前の元公開値が閾値を超え、記録した倍率が正しいことを確認する。
    引数: ready/ledger/config/short (dict)。
    返り値: tuple[int,int] の入口数と換算証跡数。
    """
    events = ledger['support_events']
    count = 0
    threshold = config['threshold_atr']
    for order in ledger['orders'][ledger['orders'][:,7] == 1]:
        row, source, side = int(order[0]), int(order[1]), int(order[3])
        previous = row-1
        assert 0 <= source < row
        old = events[events[:,0] < row]
        assert len(old)
        last = old[-1]
        assert last[1] == side and last[3] == 1
        assert 0 <= int(last[2]) <= previous
        assert short['self_valid'][previous]
        assert side*short['self_value'][previous] > threshold
        assert short['self_release_seq'][previous] <= ready['seq'][previous]
        assert short['self_source_seq'][previous] < short['self_release_seq'][previous]
        if config['support_mode'] == 3:
            assert short['peer_valid'][previous]
            assert side*short['peer_value'][previous] > threshold
            assert short['peer_release_time'][previous] < ready['time_s'][previous]
        count += 1
    strength = ledger['support_strength_events']
    expected_rows = []
    for kind, name in [(0,'normal_support_events'),(1,'support_events')]:
        rows = ledger[name][:,0].astype(np.int64)
        expected_rows.extend((int(row),kind) for row in rows)
    assert strength.shape == (len(expected_rows),8)
    if len(strength):
        np.testing.assert_array_equal(strength[:,:2],np.asarray(expected_rows))
        indices = strength[:,0].astype(np.int64)
        for column, name in [(2,'self_value'),(4,'peer_value')]:
            np.testing.assert_array_equal(strength[:,column],short[name][indices])
            np.testing.assert_array_equal(strength[:,column+1],short[name][indices]*config['support_scale'])
        np.testing.assert_array_equal(strength[:,6],np.full(len(strength),threshold))
        np.testing.assert_array_equal(strength[:,7],np.full(len(strength),config['support_scale']))
    return count, len(strength)


def main(partial, resume):
    """
    機能: 保存済み全台帳を独立FIFOと全行時価へ通し、期間集計と基準一致を検査する。
    引数: partial/resume (bool) は途中結果だけの検査と指紋一致済み結果の再利用。
    返り値: None。新しい戦略の売買計算はせず監査JSONを保存する。
    """
    folder = ROOT/'work/wave_v85/audit'
    sys.path.insert(0,str(folder))
    strategy.module('original',folder/'original.py')
    accounting = strategy.module('wave87_round5_independent_accounts',folder/'accounts.py')
    fifo = strategy.module('wave87_round5_independent_fifo',ROOT/'work/wave_v67/audit/independent_accounting.py')
    fixed = read(WORK/'事前固定.json')
    for name, value in fixed['code_SHA256'].items():
        assert digest(ROOT/name) == value, name
    inputs, _, hashes = strategy.prepare.old.load_inputs(verify=True)
    assert hashes == fixed['input_SHA256']
    shorts, proof = strategy.prepare.load(verify=True)
    totals = dict(口座数=0,注文数=0,決済脚数=0,入口根拠照合数=0,倍率証跡照合数=0,旧005完全一致口座数=0)
    reports = []
    progress = HERE/'途中独立会計.json'
    if resume and progress.exists():
        previous = read(progress)
        assert previous['全合格'] and previous['固定記録SHA256'] == digest(WORK/'事前固定.json')
        totals = {name:previous[name] for name in totals}
        reports = previous['条件別']
    for model in fixed['models']:
        for config in fixed['catalog']:
            path = WORK/model/'results'/f"{config['id']}.json"
            if partial and not path.exists():
                continue
            packet = read(path)
            lp = WORK/model/'ledgers'/f"{config['id']}.pkl"
            assert packet['config'] == config and packet['model'] == model
            assert packet['run']['code_SHA256'] == fixed['code_SHA256']
            assert packet['run']['input_SHA256'] == fixed['input_SHA256']
            assert digest(lp) == packet['ledger_SHA256']
            old = next((r for r in reports if r['モデル'] == model and r['条件'] == config['id']),None)
            if old:
                assert digest(path) == old['結果SHA256'] and digest(lp) == old['台帳SHA256']
                continue
            ledgers = pickle.loads(lp.read_bytes())
            reference = None
            if config['threshold_atr'] == .05:
                rp = WORK.parent/'round3'/model/'ledgers'/f"{config['round3_id']}.pkl"
                original = read(rp.parent.parent/'results'/f"{config['round3_id']}.json")
                assert digest(rp) == original['ledger_SHA256']
                reference = pickle.loads(rp.read_bytes())
                accounting.equal(packet['periods'],original['periods'])
            rows = []
            for actual in packet['rows']:
                key = actual['session'],actual['symbol']
                ready, ledger = inputs[key],ledgers[key]
                adapter = dict(ledger,config=ledger['settings'],trades=ledger['net_trades'],
                               fees=np.asarray(ledger['fees']).tolist())
                row, _, raw = fifo.measure(ready,adapter,model)
                np.testing.assert_array_equal(np.asarray(raw).reshape(-1,11),ledger['trades'])
                traced = accounting.trace(ready,ledger,row)
                accounting.ratios(row)
                accounting.equal(row,actual)
                accounting.time_windows(ready,ledger,traced,strategy.prior.old.old,'U')
                entry_count,event_count = entry_evidence(ready,ledger,config,shorts[key])
                totals['入口根拠照合数'] += entry_count
                totals['倍率証跡照合数'] += event_count
                if reference is not None:
                    for name,value in reference[key].items():
                        if isinstance(value,np.ndarray):
                            np.testing.assert_array_equal(value,ledger[name],err_msg=name)
                    assert ledger['net_trades'] == reference[key]['net_trades']
                    assert ledger['curve_SHA256'] == reference[key]['curve_SHA256']
                    assert ledger['raw_curve_SHA256'] == reference[key]['raw_curve_SHA256']
                    totals['旧005完全一致口座数'] += 1
                totals['口座数'] += 1
                totals['注文数'] += len(ledger['orders'])
                totals['決済脚数'] += len(ledger['trades'])
                rows.append(row)
            periods = {period:{symbol:accounting.aggregate(fifo,rows,symbol,fixed[period])
                               for symbol in ('TOPIX','NK225')} for period in ('前16','後14','全30')}
            accounting.equal(periods,packet['periods'])
            reports.append(dict(モデル=model,条件=config['id'],結果SHA256=digest(path),
                                台帳SHA256=digest(lp),全合格=True))
            value = dict(全合格=True,条件数=len(reports),**totals,条件別=reports,
                         固定記録SHA256=digest(WORK/'事前固定.json'),prepared_SHA256=proof['出力SHA256'],
                         生産会計関数呼出=False,監査器SHA256=digest(Path(__file__)))
            save('途中独立会計.json',value)
            print(model,config['id'],'独立会計・入口閾値・倍率証跡一致',flush=True)
    if not partial:
        assert len(reports) == 24 and totals['口座数'] == 1440
        assert totals['旧005完全一致口座数'] == 480
        save('全12強度条件二モデルの独立会計と公開根拠.json',read(progress))
    for name,value in fixed['code_SHA256'].items():
        assert digest(ROOT/name) == value,name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='全保存結果の独立会計と強度判定を監査する')
    parser.add_argument('--partial',action='store_true')
    parser.add_argument('--resume',action='store_true')
    args = parser.parse_args()
    main(args.partial,args.resume)
