"""全3286口座の経済、安定評価及び一軸比較を、正式完了許可後だけ独立検算する。"""

from pathlib import Path
import hashlib
import math

import numpy as np

import 共通独立読取 as R


def curves(record: dict, ledger: dict) -> np.ndarray:
    """
    機能: 注文の現金及び各源の正味保有から、全原板の清算時価を独立復元する。
    引数: record(dict)、ledger(dict)。
    返り値: ndarray[float]は源別二列の時価。原エンジン又は売買再生は呼ばない。
    """
    size = len(record['time_s'])
    multiplier,fee_unit,cap = (1000.,41.8,10) if record['symbol']=='TOPIX' else (10.,11.,20)
    valid = (record['quote_valid']&np.isfinite(record['bid'])&np.isfinite(record['ask'])
             &(record['bid']>0)&(record['ask']>record['bid']))
    latest = np.maximum.accumulate(np.where(valid,np.arange(size),-1))
    selected = np.maximum(latest,0)
    bids,asks = record['bid'][selected],record['ask'][selected]
    values = np.zeros((size,2),float)
    holdings = []
    for source in (0,1):
        orders = ledger['orders'][ledger['orders'][:,3]==source]
        index = orders[:,0].astype(np.int64)
        signed = orders[:,4]*orders[:,5]
        changes = -signed*orders[:,6]*multiplier-orders[:,9]
        cash = np.cumsum(np.bincount(index,weights=changes,minlength=size))
        held = np.cumsum(np.bincount(index,weights=signed,minlength=size))
        assert (latest[held!=0]>=0).all() and np.max(np.abs(held),initial=0)<=cap
        liquidation = np.where(held>0,bids,asks)
        return_fee = np.floor(np.abs(held)*fee_unit+1e-8)
        values[:,source] = cash+(held*liquidation*multiplier-return_fee)
        assert hashlib.sha256(values[:,source].tobytes()).hexdigest()==ledger['source_curve_column_SHA256'][source]
        holdings.append(held)
    combined = values.sum(axis=1)
    assert hashlib.sha256(values.tobytes()).hexdigest()==ledger['source_curve_SHA256']
    assert hashlib.sha256(combined.tobytes()).hexdigest()==ledger['curve_SHA256']
    long = sum(np.maximum(held,0) for held in holdings)
    short = sum(np.maximum(-held,0) for held in holdings)
    assert long.max(initial=0)<=cap and short.max(initial=0)<=cap
    assert long.max(initial=0)==ledger['stats'][0] and short.max(initial=0)==ledger['stats'][1]
    assert (long+short).max(initial=0)==ledger['stats'][8]
    return values


def path_metrics(values: np.ndarray) -> dict:
    """
    機能: ゼロ開始を含む清算時価の頂点・底点・最大下落を求める。
    引数: values(ndarray[float])。
    返り値: dictは時価経路の三指標。
    """
    path = np.r_[0.,values]
    return dict(equity_peak=float(path.max()),equity_trough=float(path.min()),
                equity_drawdown=float((np.maximum.accumulate(path)-path).max()))


def stability(rows: list[dict], config: dict, records: dict, sessions: list[str]) -> dict:
    """
    機能: 設定数量へ依存しない共通上限と全場数の安定評価を独立計算する。
    引数: rows(list[dict])、config/records(dict)、sessions(list[str])。
    返り値: dictは商品別全安定指標。実ピーク又は活動数で主分母を変えない。
    """
    result = {}
    for symbol in R.SYMBOLS:
        selected = [row for row in rows if row['symbol']==symbol and row['session'] in sessions]
        assert len(selected)==len(sessions) and len({row['session'] for row in selected})==len(sessions)
        active = [row for row in selected if row['campaigns']>0]
        red = [row for row in active if row['net'] < -1e-5]
        scale,multiplier,cap = (1,1000.,10) if symbol=='TOPIX' else (2,10.,20)
        units = {row['session']:cap*multiplier*float(records[row['session'],symbol]['price'][0])*.001 for row in selected}
        assert all(value>0 and np.isfinite(value) for value in units.values())
        values = np.array([row['net']/units[row['session']] for row in active])
        losses = np.minimum(values,0.)
        red_units = [-row['net']/units[row['session']] for row in red]
        nets = np.array([row['net'] for row in selected])
        result[symbol] = dict(configured_quantity=(config['trend_budget']+config['range_budget'])*scale,
            comparison_cap=cap,session_count=len(selected),active_sessions=len(active),no_trade_sessions=len(selected)-len(active),
            losing_sessions=len(red),positive_session_rate=sum(row['net']>1e-5 for row in active)/len(active) if active else None,
            mean_losing_session_yen=float(np.mean([-row['net'] for row in red])) if red else 0.,
            worst_session_loss_yen=max([-row['net'] for row in red],default=0.),
            downside_rms_units=math.sqrt(float(np.sum(losses**2))/len(selected)) if selected else None,
            active_downside_rms_units=float(np.sqrt(np.mean(losses**2))) if active else None,
            mean_losing_session_units=float(np.mean(red_units)) if red else 0.,worst_session_loss_units=max(red_units,default=0.),
            active_net_q25_units=float(np.quantile(values,.25)) if active else None,
            active_net_median_units=float(np.median(values)) if active else None,
            session_net_q25_yen=float(np.quantile(nets,.25)) if selected else None,
            session_net_median_yen=float(np.median(nets)) if selected else None,
            worst_intraday_drawdown_units=max([row['equity_drawdown']/units[row['session']] for row in selected],default=0.),
            comparison_units_yen=units)
    return result


def verify_nested(actual: dict, expected: dict) -> None:
    """
    機能: 独立再計算した数値又は辞書を保存表へ再帰照合する。
    引数: actual/expected(dict)。
    返り値: None。不一致は項目名で停止する。
    """
    for field,value in actual.items():
        if isinstance(value,dict):
            verify_nested(value,expected[field])
        else:
            assert value is None and expected[field] is None or value is not None and expected[field] is not None \
                and abs(float(value)-float(expected[field]))<1e-8,(field,value,expected[field])


def selection(results: dict, fixed: dict, stable: dict) -> dict:
    """
    機能: 前16だけの候補集合及び安定性採点を独立復元する。
    引数: results/fixed/stable(dict)。
    返り値: dictは正式参考と主の固定一致証拠。
    """
    formal = R.read(R.WORK/'前16参考代表.json')
    assert formal['固定SHA256']==R.digest(R.WORK/'事前固定.json') and formal['後15正式損益前選定']
    for relative,expected in formal['結果SHA256'].items():
        assert R.digest(R.ROOT/relative)==expected
    groups = [[] for _ in range(5)]
    for ident,result in results.items():
        values = [result['periods']['前16'][s] for s in R.SYMBOLS]
        if not all(value['campaigns']>=20 and value['active_sessions']>=8 for value in values):
            continue
        groups[4].append(ident)
        if not all(value['net']>0 for value in values):
            continue
        groups[3].append(ident)
        if not all(value['payoff'] is not None and value['payoff']>1 for value in values):
            continue
        groups[2].append(ident)
        if not all(value['without_best_day']['net']>0 for value in values):
            continue
        groups[1].append(ident)
        if all(value['profit_share']>=.8 for value in values):
            groups[0].append(ident)
    level = next((index for index,group in enumerate(groups) if group),5)
    pool = groups[level] if level<5 else list(results)
    scores = {}
    for ident in pool:
        values = [results[ident]['periods']['前16'][s] for s in R.SYMBOLS]
        metrics = [stable[ident]['前16'][s] for s in R.SYMBOLS]
        scores[ident] = (max(v['downside_rms_units'] if v['downside_rms_units'] is not None else 1e300 for v in metrics),
            -min(v['positive_session_rate'] if v['positive_session_rate'] is not None else -1 for v in metrics),
            max(v['worst_session_loss_units'] for v in metrics),
            -min(v['active_net_q25_units'] if v['active_net_q25_units'] is not None else -1e300 for v in metrics),
            -min(v['profit_share'] if v['profit_share'] is not None else -1 for v in values),ident)
    selected = min(pool,key=lambda ident:scores[ident])
    assert selected==formal['selected'] and set(pool)==set(formal['eligible']) and level==formal['level']
    assert formal['primary']==fixed['主']
    for ident in pool:
        assert list(scores[ident])==formal['scores'][ident],ident
    return dict(一致=True,selected=selected,主=fixed['主'],足切り段階=level,全31既知=True,
                後成績で選び直し=False,選定SHA256=R.digest(R.WORK/'前16参考代表.json'))


def compare(base: str, changed: str, ledgers: dict, fixed: dict) -> dict:
    """
    機能: 同判断の管理又は取得差、旧固有G/L、新固有G/Lに全経路差を恒等分解する。
    引数: base/changed(str)、ledgers/fixed(dict)。
    返り値: dictは商品及び源別の分解。厳密同一新規を別に示す。
    """
    result = {}
    for symbol in R.SYMBOLS:
        result[symbol] = {}
        for source,label in ((None,'全源'),(0,'J2'),(1,'O06')):
            pairs,old_only,new_only = [],[],[]
            for session in fixed['全31']:
                first = R.parent_map(ledgers[base][session,symbol],source)
                second = R.parent_map(ledgers[changed][session,symbol],source)
                pairs.extend((session,first[key],second[key]) for key in first.keys()&second.keys())
                old_only.extend((session,first[key]) for key in first.keys()-second.keys())
                new_only.extend((session,second[key]) for key in second.keys()-first.keys())
            first_net = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[base][s,symbol]['trades'] if source is None or int(t[1])==source)
            second_net = sum(float(t[11]) for s in fixed['全31'] for t in ledgers[changed][s,symbol]['trades'] if source is None or int(t[1])==source)
            management = sum(float(b[11]-a[11]) for _,a,b in pairs)
            excluded = sum(float(t[11]) for _,t in old_only)
            extra = sum(float(t[11]) for _,t in new_only)
            assert abs(second_net-first_net-management-extra+excluded)<1e-4
            strict = [(s,a,b) for s,a,b in pairs if np.array_equal(a[[2,4,5,6,8,15]],b[[2,4,5,6,8,15]])]
            cohorts = {}
            for _,a,b in pairs:
                tag = ('利益' if a[11]>0 else '損失' if a[11]<0 else 'ゼロ')+'→'+('利益' if b[11]>0 else '損失' if b[11]<0 else 'ゼロ')
                value = cohorts.setdefault(tag,dict(親=0,元収支円=0.,新収支円=0.,差円=0.))
                value['親']+=1
                value['元収支円']+=float(a[11]);value['新収支円']+=float(b[11]);value['差円']+=float(b[11]-a[11])
            def detail(values: list[tuple]) -> list[dict]:
                """
                機能: 除外又は新固有親を追跡できる判断キーへ変換する。
                引数: values(list[tuple])は場名と親配列。
                返り値: list[dict]は親の判断・取得及び純損益。
                """
                return [dict(場=s,源=int(t[1]),判断行=int(t[15]),方向=int(t[4]),枚数=int(t[5]),
                             新規行=int(t[2]),価格=float(t[6]),収支円=float(t[11])) for s,t in values]
            result[symbol][label] = dict(元収支円=first_net,新収支円=second_net,全経路差円=second_net-first_net,
                同一判断親=len(pairs),同一判断管理及び取得差円=management,厳密同一新規親=len(strict),
                厳密同一新規管理差円=sum(float(b[11]-a[11]) for _,a,b in strict),同判断だが取得又は数量が異なる親=len(pairs)-len(strict),
                同一判断符号変化=cohorts,元固有親=len(old_only),新固有親=len(new_only),
                逃した元固有利益円=sum(max(float(t[11]),0.) for _,t in old_only),避けた元固有損失円=-sum(min(float(t[11]),0.) for _,t in old_only),
                新固有利益円=sum(max(float(t[11]),0.) for _,t in new_only),新固有損失円=-sum(min(float(t[11]),0.) for _,t in new_only),
                元固有収支円=excluded,新固有収支円=extra,元固有一覧=detail(old_only),新固有一覧=detail(new_only),恒等検算=True)
    return result


def main() -> None:
    """
    機能: 根の全正式完了許可後に全53口座会計・安定指標及び一軸差を保存する。
    引数: --根許可後(bool)は必須。
    返り値: None。売買再生・候補追加・参考差替えは行わない。
    """
    R.permission()
    fixed,assembled = R.validate()
    data = R.module('独立親会計94の入力読取',R.WORK/'data_r1.py')
    material = data.load_inputs()
    ledgers,checks,stable,hashes = {},{},{},{}
    for config in fixed['条件']:
        ident = config['id']
        result = assembled['results'][ident]
        ledgers[ident] = R.load_ledgers(ident)
        checks[ident] = R.BASE.check(result,ledgers[ident],fixed)
        for row in result['rows']:
            key = row['session'],row['symbol']
            values = curves(material['prices'][key],ledgers[ident][key])
            R.equal(path_metrics(values.sum(axis=1)),row)
            for source,label in enumerate(('J2','O06')):
                R.equal(path_metrics(values[:,source]),row['sources'][label])
        stable[ident] = {}
        for period,sessions in R.partitions(fixed['全31']).items():
            for symbol in R.SYMBOLS:
                trades = np.concatenate([ledgers[ident][session,symbol]['trades'] for session in sessions])
                metric = result['periods'][period][symbol]
                for source,label in enumerate(('J2','O06')):
                    R.equal(R.totals(trades[trades[:,1]==source]),metric['sources'][label])
                for side,label in ((1,'買い'),(-1,'売り')):
                    R.equal(R.totals(trades[trades[:,4]==side]),metric['directions'][label])
            values = stability(result['rows'],config,material['prices'],sessions)
            verify_nested(values,result['stability'][period])
            stable[ident][period] = values
        for stage in ('front','back'):
            for kind,suffix in (('results','json'),('ledgers','pkl')):
                path = R.WORK/stage/kind/f'{ident}.{suffix}'
                hashes[str(path.relative_to(R.ROOT))] = R.digest(path)
        print(f'{ident}: 全62親会計・原板清算時価及び8期間安定指標を独立照合',flush=True)
    pairs = [(reference,ident) for ident,references in assembled['comparison_pairs'].items() for reference in references]
    differences = {f'{first}→{second}':compare(first,second,ledgers,fixed) for first,second in pairs}
    selected = selection(assembled['results'],fixed,stable)
    both80 = [ident for ident,result in assembled['results'].items() if all(
        result['periods']['全31'][s]['profit_share'] is not None and result['periods']['全31'][s]['profit_share']>=.8 for s in R.SYMBOLS)]
    R.save('全53条件全31の独立親会計と安定性及び一軸経路分解.json',dict(
        全合格=True,条件数=53,口座=53*62,場数=31,主=fixed['主'],
        注文=sum(value['注文'] for value in checks.values()),親=sum(value['親'] for value in checks.values()),
        商品期間群=53*8*2,会計照合=checks,清算時価全列SHA一致=True,安定性独立再計算=stable,
        一軸及び別源比較=differences,前16固定参考=selected,両商品金額80=both80,
        同一判断キー=['session','symbol','source','decisionrow','side'],
        注意=['同判断で実約定・数量・価格が異なるものは純管理差にしない。','源親のG/Lを相殺せず無取引を活動黒字へ数えない。',
              '全31は既知。両80%に活動不足があれば採択可能な成功と呼ばない。'],
        正式結果SHA256=hashes,計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))


if __name__=='__main__':
    main()
