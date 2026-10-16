"""保存済みE01_G_Uの方向偏りを、売買と相場分類に分けて事後診断する。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def sha(path):
    """
    機能: 読取成果を指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(cycles):
    """
    機能: 親組の料金後利益・損失を集計する。
    引数: cycles (list[dict]) は全返済済み親組。
    返り値: dict。0収支を黒字組に含めない。
    """
    wins = [c['net'] for c in cycles if c['net'] > 0]
    losses = [-c['net'] for c in cycles if c['net'] < 0]
    profit, loss = float(sum(wins)), float(sum(losses))
    return dict(cycles=len(cycles), winning_cycles=len(wins), losing_cycles=len(losses),
                flat_cycles=len(cycles)-len(wins)-len(losses), profit=profit, loss=loss,
                net=profit-loss, fees=float(sum(c['fees'] for c in cycles)),
                profit_share=profit/(profit+loss) if profit+loss else None,
                winning_cycle_share=len(wins)/len(cycles) if cycles else None,
                mean_win=profit/len(wins) if wins else None,
                mean_loss=loss/len(losses) if losses else None)


def main():
    """
    機能: 既知60口座の始終価格分類と親組会計を両約定モデルで照合する。
    引数: なし。
    返り値: None。新しい再生・戦略条件選択・過去成果変更を行わない。
    """
    spec = importlib.util.spec_from_file_location('wave85_direction_inputs', WORK/'prepare.py')
    prepare = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = prepare
    spec.loader.exec_module(prepare)
    inputs, _, hashes = prepare.load_inputs(verify=True)
    endpoints = {}
    for key, ready in sorted(inputs.items()):
        valid = np.flatnonzero(np.isfinite(ready['last']) & (ready['last'] > 0) & (ready['time_s'] >= ready['start']))
        first, last = int(valid[0]), int(valid[-1])
        p, q = float(ready['last'][first]), float(ready['last'][last])
        change = q/p - 1
        endpoints[key] = dict(session=key[0], symbol=key[1], start_price=p, end_price=q, change=change,
            first_time=float(ready['time_s'][first]), last_time=float(ready['time_s'][last]),
            first_seq=int(ready['seq'][first]), last_seq=int(ready['seq'][last]),
            regime='上昇' if change > .001 else '下落' if change < -.001 else '横ばい',
            sign_regime='上昇' if change > 0 else '下落' if change < 0 else '同値')
    # ----------------------------------------
    directions, markets, details, sources = [], [], [], {}
    for model in ('observed', 'specified'):
        ledger_path = WORK/model/'ledgers/E01_G_U.pkl'
        result_path = WORK/model/'results/E01_G_U.json'
        result = json.loads(result_path.read_text(encoding='utf-8'))
        assert sha(ledger_path) == result['ledger_SHA256']
        with ledger_path.open('rb') as stream:
            ledgers = pickle.load(stream)
        cycles = []
        for key, ledger in sorted(ledgers.items()):
            account = next(r for r in result['rows'] if (r['session'], r['symbol']) == key)
            local = []
            for cid in sorted({t['組'] for t in ledger['net_trades']}):
                trades = [t for t in ledger['net_trades'] if t['組'] == cid]
                assert len({t['方向'] for t in trades}) == 1
                local.append(dict(session=key[0], symbol=key[1], campaign=cid, direction='買い' if trades[0]['方向'] > 0 else '売り',
                    net=float(sum(t['収支'] for t in trades)), fees=float(sum(t['手数料'] for t in trades))))
            total = summarize(local)
            assert abs(total['net']-account['net']) < 1e-6
            assert abs(total['profit']-account['cycle_profit']) < 1e-6
            assert abs(total['loss']-account['cycle_loss']) < 1e-6
            cycles.extend(local)
            details.append(dict(model=model, **endpoints[key], **total,
                by_direction={d:summarize([c for c in local if c['direction']==d]) for d in ('買い','売り')}))
        for symbol in ('TOPIX', 'NK225'):
            for direction in ('買い', '売り'):
                directions.append(dict(model=model, symbol=symbol, direction=direction,
                    **summarize([c for c in cycles if c['symbol']==symbol and c['direction']==direction])))
            for field, labels in (('regime', ('上昇','下落','横ばい')), ('sign_regime', ('上昇','下落','同値'))):
                for regime in labels:
                    sessions = [e['session'] for e in endpoints.values() if e['symbol']==symbol and e[field]==regime]
                    group = [c for c in cycles if c['symbol']==symbol and c['session'] in sessions]
                    rows = [r for r in result['rows'] if r['symbol']==symbol and r['session'] in sessions]
                    markets.append(dict(model=model, symbol=symbol, classification=field, regime=regime, sessions=sessions,
                        session_count=len(sessions), positive_sessions=sum(r['net']>0 for r in rows),
                        negative_sessions=sum(r['net']<0 for r in rows), no_trade_sessions=sum(r['cycles']==0 for r in rows),
                        best_session_removed=float(sum(r['net'] for r in rows)-max((r['net'] for r in rows), default=0)),
                        **summarize(group), by_direction={d:summarize([c for c in group if c['direction']==d]) for d in ('買い','売り')}))
        sources[str(ledger_path.relative_to(WORK))] = sha(ledger_path)
        sources[str(result_path.relative_to(WORK))] = sha(result_path)
    output = dict(method='E01_G_U', definition=[
        '準備済み元価格CurrentPriceの各場最初と最後の有効観測から、(終値/始値)-1を算出。前日比・約定売買価格比ではない。',
        '主分類は既往の±0.1%で上昇/下落/横ばい。符号だけの上昇/下落/同値も併記する。',
        '相場分類は事後診断だけ。終値情報を入口・保有・出口・戦略選択に使っていない。',
        '親組は初回新規から全返済まで。部分利確脚を別の勝ち組として数えない。金額は手数料後。',
        '始終の方向は、途中の上昇下降経路や方向持続を表さない。30場は既知で、一般的な下落局面への有効性の証明ではない。'],
        direction_results=directions, regime_results=markets, session_results=details,
        source_SHA256=sources, input_SHA256=hashes, code_SHA256=sha(Path(__file__)), 新再生=False, 条件変更=False)
    (HERE/'方向偏り独立確認.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    for value in directions:
        if value['model']=='observed': print('DIRECTION',value)
    for value in markets:
        if value['classification']=='regime': print('REGIME',{k:v for k,v in value.items() if k not in ('sessions','by_direction')})


if __name__ == '__main__':
    main()
