"""観測可能性と期待値を分け、入口のLP/板回復及び途中停止・中心を独立診断する。"""

from pathlib import Path
from datetime import datetime
import json

import numpy as np

import 共通独立読取 as R


def point(key: tuple[str,str], row: int, material: dict, mapped: np.ndarray, wanted: dict, lane: str) -> dict:
    """
    機能: 実BBO原板に加え、その判断時に公開済みの価格源も同原seq照合へ登録する。
    引数: key(tuple[str,str])、row(int)、material(dict)、mapped(ndarray)、wanted(dict)、lane(str)。
    返り値: dictは別源を混ぜない板及び価格の診断。
    """
    value = R.point(key,row,material,mapped,wanted,lane)
    g = int(mapped[row])
    if g < 0:
        return value
    for symbol,item in value['両市場'].items():
        if not item['価格有効']:
            continue
        key_price = key[0],symbol
        if lane in ('I2','I3'):
            price = dict(商品=symbol,原本seq=item['価格原本seq'],LastPrice=item['価格値'],
                         時刻=item['価格源時計'],源種類='価格LPのみ')
            wanted.setdefault(key_price,{}).setdefault(item['価格原本seq'],[]).append(price)
        else:
            source = item['価格源index']
            price = R.raw_point(key_price,material['prices'][key_price],source,wanted)
            assert abs(price['mid']-item['価格値'])<1e-8
        item['価格原板'] = price
    return value


def attach_raw(wanted: dict) -> dict:
    """
    機能: 原seqが執行対象から除外された正常LPも、原本を直接読んで照合する。
    引数: wanted(dict)は執行BBO及び価格LPの参照点。
    返り値: dictは原本別の同seq数と指紋。板欠測を補完しない。
    """
    proof = {}
    for key,requested in wanted.items():
        path = R.ROOT/'book'/key[1]/f'{key[0]}.jsonl'
        checked = 0
        with path.open('rb') as stream:
            for seq,line in enumerate(stream):
                if seq not in requested:
                    continue
                raw = json.loads(line)
                for item in requested[seq]:
                    assert float(raw['CurrentPrice'])==item['LastPrice']
                    assert R.clock(datetime.fromisoformat(raw['CurrentPriceTime']).timestamp())==item['時刻']
                    if 'bid' in item:
                        assert float(raw['Buy1']['Price'])==item['bid'] and float(raw['Sell1']['Price'])==item['ask']
                    item['原本板'] = dict(CurrentPriceTime=raw.get('CurrentPriceTime'),
                                         買い=[raw.get(f'Buy{i}') for i in (1,2,3)],
                                         売り=[raw.get(f'Sell{i}') for i in (1,2,3)],TradingVolume=raw.get('TradingVolume'))
                checked += 1
        assert checked==len(requested),(key,checked,len(requested))
        proof['|'.join(key)] = dict(同seq数=checked,SHA256=R.digest(path))
    return proof


def qualities(session: str, g: int, material: dict, lane: str, config: dict) -> dict:
    """
    機能: ER・範囲・共同方向の既知と不明を、入力列から独立に区別する。
    引数: session(str)、g(int)、material(dict)、lane(str)、config(dict)。
    返り値: dictは両市場の価格可観測性及び現在往復の未確認原条件。
    """
    if g < 0:
        return dict(全観測可能=False,現在往復原条件=False,共同方向=None,商品={})
    all_known,low,inside = True,True,True
    common_known = True
    directions = {side:True for side in (-1,1)}
    output = {}
    for symbol in R.SYMBOLS:
        market = material['price_lanes'][lane][session]['markets'][symbol]
        current = market['current']
        value = float(current.get('value',current.get('mid'))[g])
        er,bounds = market['windows'][300],market['ranges'][180]
        now = bool(current['valid'][g] and np.isfinite(value) and value>0)
        er_known = bool(now and er['source_valid'][g] and np.isfinite(er['efficiency'][g])
                        and np.isfinite(er['total_variation'][g]) and er['total_variation'][g]>0)
        bounds_known = bool(bounds['source_valid'][g] and bounds['position_valid'][g]
                            and np.isfinite(bounds['width'][g]) and bounds['width'][g]>0
                            and np.isfinite(bounds['low'][g]) and np.isfinite(bounds['high'][g]))
        current_inside = bool(bounds_known and now and bounds['low'][g]<=value<=bounds['high'][g])
        short,long = market['windows'][30],market['windows'][300]
        returns_known = bool(now and short['source_valid'][g] and long['source_valid'][g]
                             and np.isfinite(short['ret_bp'][g]) and np.isfinite(long['ret_bp'][g]))
        common_known &= returns_known
        all_known &= er_known and bounds_known and returns_known
        low &= er_known and er['efficiency'][g]<=config['low_er']
        inside &= current_inside
        for side in (-1,1):
            directions[side] &= returns_known and side*long['ret_bp'][g]>=3. and side*short['ret_bp'][g]>0
        output[symbol] = dict(現在価格既知=now,ER300既知=er_known,ER300=float(er['efficiency'][g]),
                             TV300=float(er['total_variation'][g]),低ER=bool(er_known and er['efficiency'][g]<=config['low_er']),
                             範囲180既知=bounds_known,現在価格が直前範囲内=current_inside,共同変位既知=returns_known,
                             ret300bp=float(long['ret_bp'][g]),ret30bp=float(short['ret_bp'][g]))
    common = next((side for side in (-1,1) if directions[side]),0) if common_known else None
    return dict(全観測可能=bool(all_known),現在往復原条件=bool(all_known and low and inside and common==0),
                共同方向=common,商品=output)


def recovery_label(displacement: float | None, width: float, fraction: float) -> str:
    """
    機能: 板中値回復に対応したLPの方向と量を分類する。
    引数: displacement(float|None)、width/fraction(float)。
    返り値: strはLP不明・逆行・不変・小回復・所定幅回復。
    """
    if displacement is None or not np.isfinite(displacement):
        return 'LP不明'
    if displacement < -1e-8:
        return 'LP逆方向'
    if abs(displacement)<=1e-8:
        return 'LP不変'
    return 'LP所定幅回復' if displacement>=fraction*width-1e-8 else 'LP小回復'


def parent_detail(key: tuple[str,str], trade: np.ndarray, ledger: dict, material: dict,
                  config: dict, wanted: dict, detailed: bool=False) -> dict:
    """
    機能: 同じ親の入口板回復と観測LP、固定停止・中心及び実返済の経路を比較する。
    引数: key(tuple[str,str])、trade(ndarray)、ledger/material/config/wanted(dict)、detailed(bool)。
    返り値: dictは事後原因診断。将来値を入口又は候補変更へ逆流させない。
    """
    record = material['prices'][key]
    mapped = R.published_grid(record,material['grids'][key[0]]['grid'])
    decision,entry,exit_row,side,source = int(trade[15]),int(trade[2]),int(trade[3]),int(trade[4]),int(trade[1])
    orders = ledger['orders'][(ledger['orders'][:,2]==trade[0])&(ledger['orders'][:,3]==source)]
    assert len(orders)==2
    exit_decision = int(orders[1,1])
    lane = config.get('price_lane','I0')
    value = dict(場=key[0],商品=key[1],親=int(trade[0]),源=source,方向=side,枚数=int(trade[5]),収支円=float(trade[11]),
                 返済理由=ledger['reasons'][int(trade[13])],新規判断行=decision,新規行=entry,
                 返済判断行=exit_decision,返済行=exit_row,新規時刻=R.clock(record['time_s'][entry]),
                 新規判断=point(key,decision,material,mapped,wanted,lane),
                 新規実約定=point(key,entry,material,mapped,wanted,lane),
                 返済判断=point(key,exit_decision,material,mapped,wanted,lane),
                 返済実約定=point(key,exit_row,material,mapped,wanted,lane))
    if source!=1:
        return value
    rows = ledger['range_parent_diagnostics']
    parent = rows[rows[:,0]==trade[0]]
    assert len(parent)==1
    diagnosis = dict(zip(ledger['range_parent_columns'],map(float,parent[0])))
    assert diagnosis['net']==trade[11] and diagnosis['decision_row']==decision
    extreme_row = int(diagnosis['extreme_row'])
    state = R.state_at(ledger,decision)
    price_state = R.state_at(ledger,decision,'price')
    expected = qualities(key[0],int(mapped[decision]),material,lane,config)
    fresh = int(mapped[decision])>=0 and record['time_s'][decision]-material['grids'][key[0]]['grid'][mapped[decision]]<=10.+1e-8
    assert bool(price_state['price_observable'])==bool(fresh and expected['全観測可能'])
    extreme_mid = float((record['bid'][extreme_row]+record['ask'][extreme_row])/2.)
    current_mid = float((record['bid'][decision]+record['ask'][decision])/2.)
    assert abs(extreme_mid-diagnosis['extreme'])<1e-8
    peer = 'NK225' if key[1]=='TOPIX' else 'TOPIX'
    peer_record = material['prices'][key[0],peer]
    peer_extreme = int(state['peer_low_source'] if side==1 else state['peer_high_source'])
    peer_current = int(diagnosis['entry_peer_source'])
    own_lp = side*(record['price'][decision]-record['price'][extreme_row]) if record['price_valid'][decision] and record['price_valid'][extreme_row] else None
    peer_lp = side*(peer_record['price'][peer_current]-peer_record['price'][peer_extreme]) \
        if peer_extreme>=0 and peer_current>=0 and peer_record['price_valid'][peer_current] and peer_record['price_valid'][peer_extreme] else None
    fraction = config.get('recovery_fraction',.25)
    labels = [recovery_label(own_lp,diagnosis['width'],fraction),recovery_label(peer_lp,diagnosis['peer_width'],fraction)]
    g0,g1 = int(mapped[extreme_row]),int(mapped[decision])
    channel = material['price_lanes'][lane][key[0]]['markets'][key[1]]['current']
    channel_values = channel.get('value',channel.get('mid'))
    observed_change = side*(channel_values[g1]-channel_values[g0]) if g0>=0 and g1>=0 and channel['valid'][g0] and channel['valid'][g1] else None
    width,center = diagnosis['width'],diagnosis['center']
    stop_line = trade[6]-side*config.get('stop_widths',1.)*width
    target = center if config.get('range_target_kind','widths')!='widths' else trade[6]+side*config.get('target_widths',3.)*width
    valid_lp = np.flatnonzero(record['price_valid'][entry+1:exit_row+1])+entry+1
    valid_quote = np.flatnonzero(record['quote_valid'][entry+1:exit_row+1])+entry+1
    width_hits = valid_lp[side*(record['price'][valid_lp]-stop_line)<=0]
    center_hits = valid_lp[side*(record['price'][valid_lp]-center)>=-record['tick']*1e-8]
    quote = record['bid'] if side==1 else record['ask']
    extreme_hits = valid_quote[side*(quote[valid_quote]-diagnosis['failure_line'])<=record['tick']*1e-8]
    def first(values: np.ndarray) -> int | None:
        """
        機能: 当該親の最初の線到達行だけを取る。
        引数: values(ndarray[int])。
        返り値: int|Noneは最初行又は未到達。
        """
        return int(values[0]) if len(values) else None
    recovery_kind = '両LPも所定幅回復' if all(label=='LP所定幅回復' for label in labels) else '板回復とLP確認が不一致又は不足'
    value.update(入口当時資格=expected,価格源状態=price_state,反発固定記録=diagnosis,
                 観測極値原板=point(key,extreme_row,material,mapped,wanted,lane),
                 板回復幅pt=side*(current_mid-extreme_mid),自己LP回復幅pt=own_lp,相手LP回復幅pt=peer_lp,
                 自己LP分類=labels[0],相手LP分類=labels[1],回復分類=recovery_kind,
                 意思決定で使った価格源の極値時からの変位=observed_change,
                 意思決定価格源の回復分類=recovery_label(observed_change,width,fraction),
                 実新規後の固定中心が利益側=bool(side*(center-trade[6])>0),
                 幅停止線=float(stop_line),極値停止線=diagnosis['failure_line'],実目標線=float(target),
                 実返済までの最初幅停止行=first(width_hits),実返済までの最初極値停止行=first(extreme_hits),
                 実返済までの最初中心帰還行=first(center_hits),
                 両LP回復後に幅停止=bool(recovery_kind=='両LPも所定幅回復' and int(trade[13])==6))
    if detailed:
        chosen = set(np.linspace(entry,exit_row,min(60,exit_row-entry+1),dtype=int).tolist())
        chosen.update([extreme_row,decision,entry,exit_decision,exit_row])
        chosen.update(int(values[0]) for values in (width_hits,extreme_hits,center_hits) if len(values))
        progress = side*(quote[valid_quote]-trade[6])
        if len(progress):
            chosen.update([int(valid_quote[np.argmax(progress)]),int(valid_quote[np.argmin(progress)])])
        value['LP及び清算BBOの距離時系列'] = [dict(行=row,時刻=R.clock(record['time_s'][row]),原本seq=int(record['seq'][row]),
            LP=float(record['price'][row]) if record['price_valid'][row] else None,
            清算BBO=float(quote[row]) if record['quote_valid'][row] else None,
            新規からLP順行pt=float(side*(record['price'][row]-trade[6])) if record['price_valid'][row] else None,
            新規から清算BBO順行pt=float(side*(quote[row]-trade[6])) if record['quote_valid'][row] else None,
            中心残距離pt=float(side*(center-record['price'][row])) if record['price_valid'][row] else None,
            幅停止余地pt=float(side*(record['price'][row]-stop_line)) if record['price_valid'][row] else None,
            極値停止余地pt=float(side*(quote[row]-diagnosis['failure_line'])) if record['quote_valid'][row] else None)
            for row in sorted(chosen)]
    return value


def main() -> None:
    """
    機能: 全53の現在入口と主の追加損失親の板/LP回復を独立診断する。
    引数: --根許可後(bool)。
    返り値: None。新規注文、条件変更、事後値の入口利用は行わない。
    """
    R.permission()
    fixed,assembled = R.validate()
    financial_path = R.HERE/'全53条件全31の独立親会計と安定性及び一軸経路分解.json'
    proof = R.read(financial_path)
    assert proof['全合格'] and proof['口座']==3286 and proof['根集計SHA256']==R.digest(R.WORK/'analysis/比較結果.json')
    data = R.module('LP回復診断94の入力読取',R.WORK/'data_r1.py')
    material = data.load_inputs()
    ledgers = {config['id']:R.load_ledgers(config['id']) for config in fixed['条件']}
    summaries,wanted,samples = {},{},[]
    for config in fixed['条件']:
        ident,lane = config['id'],config.get('price_lane','I0')
        summary = {symbol:dict(ゲート受理=0,ゲート拒否=0,現在窓不明拒否=0,現在往復未確認拒否=0,
                              受理親=0,中心が実新規の利益側でない=0,中心理由なのに負net=0) for symbol in R.SYMBOLS}
        for key,ledger in ledgers[ident].items():
            record = material['prices'][key]
            mapped = R.published_grid(record,material['grids'][key[0]]['grid'])
            for event in ledger['events'][ledger['events'][:,3]==27]:
                row,accepted = int(event[0]),bool(event[11])
                state = R.state_at(ledger,row,'price')
                context = config.get('range_entry_context','legacy')
                if context!='legacy':
                    actual = qualities(key[0],int(mapped[row]),material,lane,config)
                    expected = actual['全観測可能'] and (context!='confirmed_range' or state['price_mode']==2)
                    assert bool(state['price_observable'])==actual['全観測可能'] and accepted==expected
                    if not accepted:
                        summary[key[1]]['現在窓不明拒否']+=int(not actual['全観測可能'])
                        summary[key[1]]['現在往復未確認拒否']+=int(actual['全観測可能'] and state['price_mode']!=2)
                        if len(samples)<20:
                            samples.append(dict(手法=ident,場=key[0],商品=key[1],資格=actual,
                                                原板=point(key,row,material,mapped,wanted,lane),価格源状態=state))
                summary[key[1]]['ゲート受理' if accepted else 'ゲート拒否']+=1
            for trade in ledger['trades'][ledger['trades'][:,1]==1]:
                summary[key[1]]['受理親']+=1
                parent = ledger['range_parent_diagnostics'][ledger['range_parent_diagnostics'][:,0]==trade[0]][0]
                summary[key[1]]['中心が実新規の利益側でない']+=int(trade[4]*(parent[7]-trade[6])<=0)
                summary[key[1]]['中心理由なのに負net']+=int(trade[13]==15 and trade[11]<0)
        summaries[ident] = summary
    primary = fixed['主']
    control = 'I2_G1_S0_T1'
    primary_details,classes = {},{}
    for symbol in R.SYMBOLS:
        primary_details[symbol] = []
        classes[symbol] = {}
        for session in fixed['全31']:
            key = session,symbol
            old = R.parent_map(ledgers[control][key],1)
            for parent_key,trade in R.parent_map(ledgers[primary][key],1).items():
                detail = parent_detail(key,trade,ledgers[primary][key],material,assembled['results'][primary]['config'],wanted)
                detail['旧源LP対照の同判断あり'] = parent_key in old
                detail['原本LPへの変更で新固有損失'] = parent_key not in old and trade[11]<0
                primary_details[symbol].append(detail)
                if detail['原本LPへの変更で新固有損失']:
                    tag = detail['回復分類']+'／'+detail['返済理由']
                    item = classes[symbol].setdefault(tag,dict(親=0,損失円=0.))
                    item['親']+=1;item['損失円']-=float(trade[11])
    raw = attach_raw(wanted)
    R.save('全53入口の現在価格資格と回復停止中心の独立診断.json',dict(
        全合格=True,条件数=53,口座=3286,主=primary,全53ゲート及び固定中心診断=summaries,
        現在入口拒否の具体板20例=samples,主の全受理親=primary_details,
        主の原本LP変更で新固有損失のLP板回復分類=classes,原本同seq照合=raw,
        注意=['LP回復は極値板行及び現在の公開済み相手板行のCurrentPrice値で分類する。価格窓の厳密過去源との差も別記する。',
              '板中値回復とLPが同じ方向でも、その後に中心まで継続する予測が正しいとは限らない。',
              '窓観測の修正自体と、追加した回復機会の期待値を分ける。事後分類を既存入口へ使わない。',
              '板snapshotだけで焦り、隠れ注文、補充、取消、参加者の意図を断定しない。代理時計は真受信時計でない。'],
        根拠SHA256={str(financial_path.relative_to(R.ROOT)):R.digest(financial_path)},
        計算コードSHA256=R.digest(Path(__file__)),**R.provenance()))
    print('現在窓とLP/板回復及び主の追加損失親を独立診断しました',flush=True)


if __name__=='__main__':
    main()
