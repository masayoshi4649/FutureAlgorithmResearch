"""完成会計だけを独立再集計し、改修で救った損失と捨てた利益を検査する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import pickle
import statistics

import numpy as np

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parents[1]
FINAL = TASK/'最終統合の価格モデル別比較と公開会計.json'
EXTRA = TASK/'gated_bbo126/GとGU及び低R利益床の全四十一場BBO会計.json'
OLD = TASK/'engine/bbo_next/全十六条件の次原行BBO会計.json'
PREPARED = TASK/'input_audit/attempt2/全四十一場の元入力と新市場特徴の非金融準備.json'
JST = timezone(timedelta(hours=9))


def read(path: Path) -> dict:
    """
    機能: 保存済み小JSONを診断目的で読む。
    引数: path(Path)は完成会計又は固定参照。
    返り値: dictは内容。金融再生は行わない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def independent_metrics(rows: list[dict], metadata: dict) -> dict:
    """
    機能: 最低条件と価格幅目標を、選定関数を呼ばず別々に再集計する。
    引数: rows(list[dict])は一手法一商品の四十一場、metadata(dict)は始値と採点区分。
    返り値: dictは参加・上位依存・上下・最悪損失・価格幅の独立数値。
    """
    assert len(rows) == 41
    positive = sorted((r['net'] for r in rows if r['net'] > 0.),reverse=True)
    mean_positive = statistics.mean(positive) if positive else 0.
    cap,mult = (10,1000.) if rows[0]['symbol'] == 'TOPIX' else (20,10.)
    values = dict(net=sum(r['net'] for r in rows),red=sum(r['net'] < 0. for r in rows),
        no_entry=sum(r['entry_orders'] == 0 for r in rows),median=statistics.median(r['net'] for r in rows),
        excluding_best_three=sum(r['net'] for r in rows)-sum(positive[:3]),
        worst=min(r['net'] for r in rows),average_positive=mean_positive,
        worst_to_typical=-min(0.,min(r['net'] for r in rows))/mean_positive if mean_positive else None,
        average_price_fraction=statistics.mean(r['net']/(cap*mult*metadata[r['session'],r['symbol']]['first']) for r in rows),
        up_net=sum(r['net'] for r in rows if metadata[r['session'],r['symbol']]['regime'] == '上昇'),
        down_net=sum(r['net'] for r in rows if metadata[r['session'],r['symbol']]['regime'] == '下落'))
    values['minimum_passed'] = (values['no_entry'] == 0 and values['net'] > 0. and values['median'] > 0.
        and values['excluding_best_three'] > 0. and values['up_net'] > 0. and values['down_net'] > 0.)
    values['price_target_passed'] = values['no_entry'] == 0 and values['average_price_fraction'] >= .005
    return values


def effect(rows: dict, base: str, changed: str) -> dict:
    """
    機能: 全経路の二条件の場差を集計し、改善だけを抜き出す誤認を防ぐ。
    引数: rows(dict)は手法・場・商品索引、base/changed(str)は固定比較。
    返り値: dictは改善場と悪化場、原版黒字を削った場、原版赤字を救った場。
    """
    values = {}
    for symbol in ('TOPIX','NK225'):
        deltas = []
        for method,scene,product in rows:
            if method != base or product != symbol:
                continue
            old,new = rows[base,scene,symbol],rows[changed,scene,symbol]
            delta = new['net']-old['net']
            deltas.append(dict(session=scene,base_net=old['net'],new_net=new['net'],delta=delta,
                base_entries=old['entry_orders'],new_entries=new['entry_orders']))
        assert len(deltas) == 41
        values[symbol] = dict(net_delta=sum(r['delta'] for r in deltas),
            improved=sum(r['delta'] > 0. for r in deltas),worsened=sum(r['delta'] < 0. for r in deltas),
            removed_losses=sum(max(0.,r['delta']) for r in deltas if r['base_net'] < 0.),
            damaged_positive=sum(min(0.,r['delta']) for r in deltas if r['base_net'] > 0.),
            best=sorted(deltas,key=lambda r:-r['delta'])[:3],
            worst=sorted(deltas,key=lambda r:r['delta'])[:3],rows=deltas)
    return dict(base=base,changed=changed,products=values)


def payload(item: dict, logs: list, purpose: str) -> bytes:
    """
    機能: 許可された最大三場の所有保存資料を一読し指紋を記録する。
    引数: item(dict)はpath/sha256、logs(list)は読取簿、purpose(str)は用途。
    返り値: bytesは検証済み資料。原本は対象にしない。
    """
    path = (ROOT/item['path']).resolve()
    assert path.is_relative_to(ROOT/'work')
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == item['sha256']
    logs.append(dict(path=item['path'],sha256=item['sha256'],reads=1,purpose=purpose))
    return content


def time_at(ready: dict, row: int) -> str:
    """
    機能: 保存代理価格時計を日本時間の表示へ変換する。
    引数: ready(dict)、row(int)は入力と既知行番号。
    返り値: strは日時。実受信遅延を示す時計とは解釈しない。
    """
    return datetime.fromtimestamp(float(ready['time_s'][row]),JST).isoformat()


def parent_view(data: dict, cycle: np.ndarray, ready: dict, quotes: dict) -> dict:
    """
    機能: 保存実玉の親損益と正常気配だけの最高清算益を具体時刻へ戻す。
    引数: data(dict)は保存会計、cycle(ndarray)は完成親、ready/quotes(dict)は所有入力。
    返り値: dictは親会計と実建値の説明。新しい売買判定を実行しない。
    """
    cid,begin,end = map(int,cycle[:3])
    orders = data['orders'][data['orders'][:,2] == cid]
    entry = orders[orders[:,7] == 1.][0]
    mult = 1000. if ready['symbol'] == 'TOPIX' else 10.
    indices = np.arange(begin,end+1)
    valid = np.asarray(quotes['quote_valid'])[indices].astype(bool)
    valid &= np.isfinite(quotes['bid'][indices]) & np.isfinite(quotes['ask'][indices])
    valid &= (quotes['bid'][indices] > 0.) & (quotes['bid'][indices] < quotes['ask'][indices])
    known = indices[valid]
    start_cash = float(data['curve'][begin,1])
    pnl = (data['curve'][known,0]-start_cash)*mult
    peak = int(known[int(np.argmax(pnl))]) if len(known) else None
    return dict(net=float(cycle[3]*mult),entry_time=time_at(ready,begin),exit_time=time_at(ready,end),
        exit_reason=int(cycle[9]),entry_price=float(entry[5]),
        entry_spread=float(quotes['ask'][begin]-quotes['bid'][begin]),initial_atr=float(cycle[5]),
        maximum_observed_liquidation_pnl=float(np.max(pnl)) if len(pnl) else None,
        peak_time=time_at(ready,peak) if peak is not None else None,
        unknown_quote_rows=int(len(indices)-len(known)))


def concrete(old: dict,extra: dict,prepared: dict) -> tuple[list,list]:
    """
    機能: 事前固定した超幅二場と利益返し一場で、保存親組の差を具体確認する。
    引数: old/extra/prepared(dict)は完成会計と固定packet参照。
    返り値: tuple[list,list]は親別比較と三場以内の所有再読記録。新金融は零。
    """
    targets = [('2026-10-02_Night','TOPIX'),('2026-10-15_Night','NK225'),('2026-10-16_Day','TOPIX')]
    packets = {r['session']:r for r in prepared['packets']}
    oldcache = {(r['session'],r['symbol']):r for r in old['cache']}
    newcache = {(r['session'],r['symbol']):r for r in extra['cache']}
    traces = {(r['session'],r['symbol'],r['paper_source']):r for r in extra['quote_gate_traces']}
    logs, output = [],[]
    variants = ('E01_P025','E01_P050','E01_P075','E01_Q','E01_Q_P025','E01_Q_P050','E01_Q_P075')
    for scene,symbol in targets:
        packet = pickle.loads(payload(packets[scene],logs,'事前固定三場の通知時刻と実約定時刻'))
        ready = packet['inputs'][scene,symbol]
        quotes = packet['quotes'][scene,symbol]
        mult = 1000. if symbol == 'TOPIX' else 10.
        with np.load(io.BytesIO(payload(oldcache[scene,symbol],logs,'旧原版の親別比較')),allow_pickle=False) as arrays:
            baseline = {field:arrays['E01__'+field] for field in ('orders','cycles','execution_events','curve')}
        with np.load(io.BytesIO(payload(newcache[scene,symbol],logs,'新低RとQの親別比較')),allow_pickle=False) as arrays:
            alternatives = {method:{field:arrays[method+'__'+field] for field in ('orders','cycles','execution_events','curve')} for method in variants}
        parents = []
        gate_by_parent = {r['parent']:r for r in traces[scene,symbol,'E01']['parents']}
        for cycle in baseline['cycles']:
            cid = int(cycle[0])
            orders = baseline['orders'][baseline['orders'][:,2] == cid]
            entry = orders[orders[:,7] == 1.][0]
            parent = dict(parent=cid,entry_time=time_at(ready,int(entry[0])),entry_price=float(entry[5]),
                initial_atr=float(cycle[5]),old_net=float(cycle[3]*mult),old_exit_time=time_at(ready,int(cycle[2])),
                old_reason=int(cycle[9]),quote_gate=gate_by_parent[cid],variants=[])
            parent['baseline_details'] = parent_view(baseline,cycle,ready,quotes)
            for method,data in alternatives.items():
                selected = data['cycles'][data['cycles'][:,0] == cid]
                events = data['execution_events'][data['execution_events'][:,2] == cid]
                raises = events[events[:,1] == 12.]
                parent['variants'].append(dict(method=method,participated=bool(len(selected)),
                    net=float(selected[0,3]*mult) if len(selected) else 0.,
                    delta=float((selected[0,3] if len(selected) else 0.)*mult-cycle[3]*mult),
                    exit_time=time_at(ready,int(selected[0,2])) if len(selected) else None,
                    exit_reason=int(selected[0,9]) if len(selected) else None,
                    details=parent_view(data,selected[0],ready,quotes) if len(selected) else None,
                    floor_times=[time_at(ready,int(event[0])) for event in raises]))
            parents.append(parent)
        output.append(dict(session=scene,symbol=symbol,parents=parents))
    assert len({scene for scene,_ in targets}) == 3 and len(logs) == 9
    return output,logs


def execute() -> None:
    """
    機能: 完成後の全条件を独立採点し、因子差と固定三場だけの具体反証を保存する。
    引数: なし。
    返り値: None。金融計算・原本読取・ＡＰＩは零。
    """
    final,extra,old,prepared = map(read,(FINAL,EXTRA,OLD,PREPARED))
    assert all(value['passed'] for value in (final,extra,old,prepared))
    rows = old['rows']+extra['rows']
    assert len(rows) == 5658
    index = {(r['method'],r['session'],r['symbol']):r for r in rows}
    metadata = {(r['session'],r['symbol']):r for r in old['metadata']}
    comparisons = []
    for model in final['models']:
        for ranked in model['ranking']:
            if model['id'] != 'next_normal_bbo':
                continue
            products = {}
            for symbol in ('TOPIX','NK225'):
                chosen = [r for r in rows if r['method'] == ranked['id'] and r['symbol'] == symbol]
                independent = independent_metrics(chosen,metadata)
                parent = ranked['products'][symbol]
                for field in ('net','red','no_entry','median','excluding_best_three','worst','average_positive','worst_to_typical','average_price_fraction'):
                    assert independent[field] == parent[field] or np.isclose(independent[field],parent[field]),(ranked['id'],symbol,field)
                assert independent['up_net'] == parent['regimes']['上昇']['net']
                assert independent['down_net'] == parent['regimes']['下落']['net']
                products[symbol] = independent
            assert ranked['minimum_passed'] == all(p['minimum_passed'] for p in products.values())
            comparisons.append(dict(method=ranked['id'],products=products,minimum_passed=ranked['minimum_passed']))
    pairs = []
    for source,base in (('E01','E01'),('G','G_E01'),('GU','GU_E01')):
        pairs.append(effect(index,base,source+'_Q'))
        for threshold in ('P025','P050','P075'):
            pairs.append(effect(index,base,source+'_'+threshold))
            pairs.append(effect(index,source+'_Q',source+'_Q_'+threshold))
    cases,logs = concrete(old,extra,prepared)
    target = HERE/'最終全条件の独立再集計と三場診断.json'
    assert not target.exists()
    report = dict(passed=True,comparisons=comparisons,effects=pairs,concrete=cases,diagnostic_read_log=logs,
        market_scene_rereads=3,financial_replays=0,original_market_reads=0,API=0,
        source_jsons=[dict(path=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (FINAL,EXTRA,OLD,PREPARED)],
        causality='保存全経路差はこの既知入力と条件での反実仮想差。未来相場での有効性・気配幅の原因・実ネットワーク遅延は証明しない。')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('独立会計比較',len(comparisons),'因子比較',len(pairs),'診断三場',len(cases),flush=True)


if __name__ == '__main__':
    execute()
