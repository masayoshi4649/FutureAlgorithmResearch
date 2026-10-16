"""前16の実親会計から参考選定を独立再構成する。根score/selectは呼ばない。"""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
SYMBOLS=('TOPIX','NK225')


def read(path: Path) -> object:
    """
    機能: 固定仕様又は許可された前16だけの保存台帳を読む。
    引数: path(Path)。
    返り値: objectはJSON又はpickle。後15の損益は読まない。
    """
    with path.open('rb') as stream:
        return pickle.load(stream) if path.suffix=='.pkl' else json.loads(stream.read().decode('utf-8'))


def sha(path: Path) -> str:
    """
    機能: 保存資料の内容を分割して指紋化する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def guard(base: Path, fixed: dict) -> None:
    """
    機能: 全38前16の完結と後15未作成を検査して選定前後の混合を拒否する。
    引数: base(Path)は作業又は人工根、fixed(dict)。
    返り値: None。不完全front又は既存back成果は例外で拒否する。
    """
    ids={config['id'] for config in fixed['条件']}
    assert len(ids)==38 and len(fixed['前16'])==16
    assert {p.stem for p in (base/'front/results').glob('*.json')}==ids
    assert {p.stem for p in (base/'front/ledgers').glob('*.pkl')}==ids
    assert not list((base/'back').rglob('*.json')) and not list((base/'back').rglob('*.pkl'))


def close(actual: object, expected: object, field: str = '') -> None:
    """
    機能: 独立会計の数値と正式保存値を浮動演算の丸めを除いて照合する。
    引数: actual/expected(object)、field(str)。
    返り値: Noneは一致確認。候補判定や順位へ公差による救済を足さない。
    """
    if actual is None or expected is None:
        assert actual is expected,field
    elif isinstance(expected,(float,int)):
        assert math.isfinite(float(actual)) and math.isfinite(float(expected)),field
        assert math.isclose(float(actual),float(expected),rel_tol=1e-10,abs_tol=1e-7),field
    else:
        assert actual==expected,field


def parent_totals(trades: object, symbol: str) -> dict:
    """
    機能: 実親の建値・返済値・数量と両側料から費用後G/Lを独立計算する。
    引数: trades(ndarray[float])は16列、symbol(str)。
    返り値: dictは親別利益・損失・収支・枚数・payoff。
    """
    assert trades.ndim==2 and trades.shape[1]==16
    value,unit=(1000.,41.8) if symbol=='TOPIX' else (10.,11.)
    profit=loss=gross_total=fees=0.;wins=loses=winning_lots=losing_lots=flat_lots=0
    for parent in trades:
        side,quantity=int(parent[4]),int(parent[5]);assert side in (-1,1) and quantity>0
        gross=side*(float(parent[7])-float(parent[6]))*quantity*value
        fee=math.floor(quantity*unit+1e-8)
        close(parent[8],fee,'建料');close(parent[9],fee,'返済料');close(parent[10],gross,'親gross')
        net=gross-float(parent[8])-float(parent[9]);close(parent[11],net,'親net')
        gross_total+=gross;fees+=float(parent[8])+float(parent[9])
        if net>1e-5:profit+=net;wins+=1;winning_lots+=quantity
        elif net< -1e-5:loss-=net;loses+=1;losing_lots+=quantity
        else:flat_lots+=quantity
    average_win=profit/wins if wins else None;average_loss=loss/loses if loses else None
    return dict(profit=profit,loss=loss,net=profit-loss,gross=gross_total,fees=fees,campaigns=len(trades),
        winning_campaigns=wins,losing_campaigns=loses,flat_campaigns=len(trades)-wins-loses,
        winning_lots=winning_lots,losing_lots=losing_lots,flat_lots=flat_lots,
        lots=winning_lots+losing_lots+flat_lots,profit_share=profit/(profit+loss) if profit+loss else None,
        average_win=average_win,average_loss=average_loss,
        payoff=average_win/average_loss if average_win is not None and average_loss is not None and average_loss>0 else None)


def quantile(values: list[float], fraction: float) -> float | None:
    """
    機能: NumPy又は根の集計関数を使わず線形分位を計算する。
    引数: values(list[float])、fraction(float)。
    返り値: float|Noneは分位又は空系列の不明。
    """
    if not values:return None
    ordered=sorted(values);position=(len(ordered)-1)*fraction
    low,high=math.floor(position),math.ceil(position)
    return ordered[low]+(ordered[high]-ordered[low])*(position-low)


def summarize(config: dict, rows: list[dict], sessions: list[str], first_prices: dict) -> dict:
    """
    機能: 親会計を場・日・商品へ集め、固定共通上限と全16分母で安定性を算出する。
    引数: config/first_prices(dict)、rows(list[dict])、sessions(list[str])。
    返り値: dictは独立period/stability。無取引を活動黒字へ含めない。
    """
    periods={};stability={}
    for symbol in SYMBOLS:
        selected=[next(row for row in rows if row['session']==session and row['symbol']==symbol) for session in sessions]
        active=[row for row in selected if row['campaigns']>0];red=[row for row in active if row['net']< -1e-5]
        profit=sum(row['profit'] for row in selected);loss=sum(row['loss'] for row in selected)
        wins=sum(row['winning_campaigns'] for row in selected);loses=sum(row['losing_campaigns'] for row in selected)
        day_nets={}
        for row in selected:
            day=row['session'][:10];day_nets[day]=day_nets.get(day,0.)+row['net']
        best=max(day_nets,key=day_nets.get) if day_nets else None
        rest=[row for row in selected if row['session'][:10]!=best]
        quantity=config['trend_budget']*(1 if symbol=='TOPIX' else 2)
        cap,value=(10,1000.) if symbol=='TOPIX' else (20,10.)
        units={session:cap*value*first_prices[session,symbol]*.001 for session in sessions}
        assert all(math.isfinite(unit) and unit>0 for unit in units.values())
        normalized=[row['net']/units[row['session']] for row in active]
        losses=[min(net,0.) for net in normalized];red_units=[-row['net']/units[row['session']] for row in red]
        positive=sum(row['net']>1e-5 for row in active)
        periods[symbol]=dict(profit=profit,loss=loss,net=profit-loss,
            campaigns=sum(row['campaigns'] for row in selected),active_sessions=len(active),
            profit_share=profit/(profit+loss) if profit+loss else None,
            payoff=(profit/wins)/(loss/loses) if wins and loses else None,
            best_day=best,without_best_day=dict(net=sum(row['net'] for row in rest)))
        stability[symbol]=dict(configured_quantity=quantity,comparison_cap=cap,session_count=len(selected),
            active_sessions=len(active),no_trade_sessions=len(selected)-len(active),losing_sessions=len(red),
            positive_session_rate=positive/len(active) if active else None,
            mean_losing_session_yen=sum(-row['net'] for row in red)/len(red) if red else 0.,
            worst_session_loss_yen=max([-row['net'] for row in red],default=0.),
            downside_rms_units=math.sqrt(sum(net*net for net in losses)/len(selected)),
            active_downside_rms_units=math.sqrt(sum(net*net for net in losses)/len(active)) if active else None,
            mean_losing_session_units=sum(red_units)/len(red_units) if red else 0.,
            worst_session_loss_units=max(red_units,default=0.),active_net_q25_units=quantile(normalized,.25),
            active_net_median_units=quantile(normalized,.5),session_net_q25_yen=quantile([row['net'] for row in selected],.25),
            session_net_median_yen=quantile([row['net'] for row in selected],.5),comparison_units_yen=units)
    return dict(config=config,periods=periods,stability=stability)


def ranking(result: dict) -> tuple:
    """
    機能: 両商品の悪い側の固定順から参考順位を独立計算する。
    引数: result(dict)は独立summary。
    返り値: tupleはRMS・黒字率・最大赤字・q25・利益割合・IDの順。
    """
    stable=[result['stability'][symbol] for symbol in SYMBOLS]
    totals=[result['periods'][symbol] for symbol in SYMBOLS]
    rms=[row['downside_rms_units'] if row['downside_rms_units'] is not None else 1e300 for row in stable]
    rates=[row['positive_session_rate'] if row['positive_session_rate'] is not None else -1 for row in stable]
    lower=[row['active_net_q25_units'] if row['active_net_q25_units'] is not None else -1e300 for row in stable]
    shares=[row['profit_share'] if row['profit_share'] is not None else -1 for row in totals]
    return (max(rms),-min(rates),max(row['worst_session_loss_units'] for row in stable),
            -min(lower),-min(shares),result['config']['id'])


def choose(results: list[dict]) -> dict:
    """
    機能: 両商品20親8場と黒字・損小利大・最大日除外・80%の優先集合を独立に選ぶ。
    引数: results(list[dict])は全条件の独立集計。
    返り値: dictは代表・優先段階・候補集合・全候補score。
    """
    active=[r for r in results if all(r['periods'][s]['campaigns']>=20 and r['periods'][s]['active_sessions']>=8 for s in SYMBOLS)]
    positive=[r for r in active if all(r['periods'][s]['net']>0 for s in SYMBOLS)]
    good=[r for r in positive if all(r['periods'][s]['payoff'] is not None and r['periods'][s]['payoff']>1 for s in SYMBOLS)]
    robust=[r for r in good if all(r['periods'][s]['without_best_day']['net']>0 for s in SYMBOLS)]
    target=[r for r in robust if all(r['periods'][s]['profit_share']>=.8 for s in SYMBOLS)]
    groups=(target,robust,good,positive,active,results)
    level=next(i for i,group in enumerate(groups) if group);pool=groups[level]
    return dict(selected=min(pool,key=ranking)['config']['id'],level=level,
                eligible=[r['config']['id'] for r in pool],scores={r['config']['id']:ranking(r) for r in pool})


def inspect(base: Path, fixed: dict, first_prices: dict) -> list[dict]:
    """
    機能: 前16台帳の実親から全38条件の保存rows・集計・安定性を独立再計算する。
    引数: base(Path)、fixed/first_prices(dict)。
    返り値: list[dict]は正答を根関数へ委譲しない独立summary。
    """
    guard(base,fixed);sessions=fixed['前16'];answers=[]
    for config in fixed['条件']:
        path=base/'front/ledgers'/(config['id']+'.pkl');saved=read(base/'front/results'/(config['id']+'.json'))
        assert saved['config']==config and saved['ledger_SHA256']==sha(path)
        ledger=read(path);assert set(ledger)=={(session,symbol) for session in sessions for symbol in SYMBOLS}
        assert {(row['session'],row['symbol']) for row in saved['rows']}==set(ledger) and len(saved['rows'])==32
        rows=[]
        for session in sessions:
            for symbol in SYMBOLS:
                key=session,symbol;stored=ledger[key];computed=parent_totals(stored['trades'],symbol)
                row=next(row for row in saved['rows'] if (row['session'],row['symbol'])==key)
                for field,value in computed.items():close(row[field],value,config['id']+' '+field)
                rows.append(dict(session=session,symbol=symbol,**computed))
        summary=summarize(config,rows,sessions,first_prices)
        for symbol in SYMBOLS:
            actual=saved['periods']['前16'][symbol]
            for field,value in summary['periods'][symbol].items():
                if field=='without_best_day':close(actual[field]['net'],value['net'],'最大日除外net')
                else:close(actual[field],value,'期間 '+field)
            for field,value in summary['stability'][symbol].items():
                if isinstance(value,dict):
                    assert actual is not None
                    for session,unit in value.items():close(saved['stability'][symbol][field][session],unit,'比較単位')
                else:close(saved['stability'][symbol][field],value,'安定性 '+field)
        answers.append(summary)
    return answers


def main() -> None:
    """
    機能: 根の前16完了/select通知後、後15未作成の間だけ独立参考選定を照合する。
    引数: --root-front-select-complete(bool)は根から段階明示を受領した場合だけ指定する。
    返り値: Noneは選定及び全前16親会計の独立証跡。新売買は実行しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--root-front-select-complete',action='store_true');args=parser.parse_args()
    assert args.root_front_select_complete,'前16完了と根selectの明示前は正式結果を読みません'
    fixed_path=WORK/'事前固定.json';selected_path=WORK/'前16参考代表.json'
    fixed=read(fixed_path);guard(WORK,fixed);selected=read(selected_path)
    assert selected['後15正式損益前選定'] and selected['固定SHA256']==sha(fixed_path)
    for relative,expected in fixed['SHA256'].items():
        assert sha(ROOT/relative)==expected,relative
    front_paths=sorted((WORK/'front/results').glob('*.json'))
    current_front={str(path.relative_to(ROOT)):sha(path) for path in front_paths}
    assert selected['結果SHA256']==current_front,'選定時の前16結果指紋'
    spec=importlib.util.spec_from_file_location('参考選定の価格入力読取95',WORK/'data.py')
    data=importlib.util.module_from_spec(spec);spec.loader.exec_module(data)
    material=data.previous.load_inputs();first_prices={(session,symbol):float(material['prices'][session,symbol]['price'][0])
        for session in fixed['前16'] for symbol in SYMBOLS}
    input_paths=list(material['paths'])
    del material
    results=inspect(WORK,fixed,first_prices);independent=choose(results)
    assert independent['selected']==selected['selected'] and independent['level']==selected['level']
    assert independent['eligible']==selected['eligible']
    assert set(independent['scores'])==set(selected['scores'])
    for ident,values in independent['scores'].items():
        for i,value in enumerate(values):close(selected['scores'][ident][i],value,'score '+ident)
    paths=[Path(__file__),fixed_path,selected_path,WORK/'research.py',WORK/'セッション安定性の事前評価.json',WORK/'data.py',*input_paths]
    paths+=list((WORK/'front/results').glob('*.json'))+list((WORK/'front/ledgers').glob('*.pkl'))
    proof=dict(全合格=True,条件数=38,前16口座数=1216,参考代表=independent['selected'],段階=independent['level'],
        候補集合=independent['eligible'],独立score=independent['scores'],根score及びselect呼出=0,
        後15損益閲覧=0,新売買実行=0,全31既知=True,共通cap及び全16分母=True,
        SHA256={str(path.relative_to(ROOT)):sha(path) for path in paths},API取得=0,実注文=0)
    path=HERE/'後15未作成の全38前16実親会計と安定順による独立参考選定.json'
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k not in ('SHA256','独立score')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
