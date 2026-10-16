"""先に選抜済みの保存実台帳だけを読み、損失軽減と勝ち喪失を別に診断する。"""

import argparse
from collections import Counter
import gc

import numpy as np

import tools

TICK={'TOPIX':.5,'NK225':10.}
QUANTITY={'TOPIX':5,'NK225':10}
FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def clean(value: object) -> object:
    """
    機能: 診断用のnumpy数値を有限JSONへ変換する。
    引数: value(object)はnumpy数値又は入れ子データ。
    返り値: objectは標準型。未知floatはnullにし、数値を有利へ補わない。
    """
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,(np.floating,float)):return float(value) if np.isfinite(value) else None
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.bool_):return bool(value)
    return value


def at(value: object, row: int) -> float:
    """
    機能: 圧縮曲線の当行値だけを過去保持で取得する。
    引数: value(dict|ndarray)、row(int)は保存曲線とnormal行。
    返り値: floatは実当行値。未来曲線値を使わない。
    """
    if isinstance(value,dict):
        i=np.searchsorted(value['rows'],row,side='right')-1;assert i>=0
        return float(value['values'][i])
    return float(value[row])


def snapshot(account: dict, ledger: dict, row: int, window: int) -> dict:
    """
    機能: 実normal行の気配・残玉・全normal更新票を同原seqへ結ぶ。
    引数: account/ledger(dict)、row/window(int)は保存口座・台帳・当行・窓秒。
    返り値: dictは当時情報。Last時計を受信時計とは説明しない。
    """
    q=account['quotes'];v=account['votes'][str(window)]
    side=int(np.sign(at(ledger['long_qty'],row)-at(ledger['short_qty'],row)))
    total=int(v['up_votes'][row]+v['down_votes'][row])
    balance=float(v['balance'][row]) if np.isfinite(v['balance'][row]) else None
    unit=TICK[account['symbol']]*QUANTITY[account['symbol']]*tools.VALUE[account['symbol']]
    liq=at(ledger['liquidation_yen'],row)
    return dict(**tools.clock(account,row),bid=float(q['bid'][row]),ask=float(q['ask'][row]),
        正常気配=bool(q['quote_valid'][row]),実残玉方向=side,実残買枚数=at(ledger['long_qty'],row),
        実残売枚数=at(ledger['short_qty'],row),全口座料金後清算=liq,初回全枚数呼値換算清算=liq/unit,
        当時票=dict(窓秒=window,既知=bool(v['known'][row]),不明理由=int(v['reason'][row]),
        買票=int(v['up_votes'][row]),売票=int(v['down_votes'][row]),総票=total,買方向釣合い=balance,
        持ち方向釣合い=side*balance if balance is not None and side else None,
        reference_raw_row=int(v['reference_raw_row'][row]),first_vote_raw_row=int(v['first_vote_raw_row'][row]),
        candidate_raw_row=int(v['candidate_raw_row'][row])))


def parent_detail(ledger: dict, account: dict, cid: int, window: int) -> dict:
    """
    機能: 指定実親の新規/返済・部分返済・事後最大清算時価を保存気配から測る。
    引数: ledger/account(dict)、cid/window(int)は保存実親と票窓。
    返り値: dictは実損益/時刻/価格と事後経路。仮想的な別返済を再生しない。
    """
    p=tools.parents(ledger)[cid];orders=[]
    for i in np.flatnonzero(ledger['orders'][:,2]==cid):
        o=ledger['orders'][i];row,decision=int(o[0]),int(o[1])
        orders.append(dict(新規=bool(o[7]),side=int(o[3]),quantity=int(o[4]),price=float(o[5]),
            reason=int(o[6]),uid=int(ledger['order_uids'][i]),
            判断=snapshot(account,ledger,decision,window),約定=snapshot(account,ledger,row,window)))
    return dict(親=clean(p),実注文=orders,事後経路=tools.parent_path(ledger,account,cid))


def main() -> None:
    """
    機能: 固定済み具体例だけを必要cache/台帳各一読で検算し、全6集計と反例へ結ぶ。
    引数: CLI --selected-examples-fixed(bool)は選抜JSONが保存済みである指定。
    返り値: None。新金融・原NPZ・原板/API・政策閾値変更をしない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--selected-examples-fixed',action='store_true')
    assert parser.parse_args().selected_examples_fixed
    plan,plansha=tools.read(tools.HERE/'具体例の読取前選抜計画.json')
    result,resultsha=tools.read(tools.SOURCE/'finance/結果.json');assert resultsha==plan['金融結果SHA256']
    fixed,fixedsha=tools.read(tools.SOURCE/'金融前の固定.json')
    meta,metasha=tools.read(tools.SOURCE/'全33場の保有中取引更新票.json')
    choices=[v for v in plan['選抜'] if v['選抜'] is not None];counts=Counter();refs={};records=[]
    ledgers={}
    def load(item: dict) -> dict:
        """
        機能: 選抜された保存台帳を同bytes一読し、同じ位置は診断内で再利用する。
        引数: item(dict)は固定されたpath/SHA256。
        返り値: dictは元実台帳。原出力を変更しない。
        """
        path=item['path']
        if path not in ledgers:
            value,sha=tools.read(tools.ROOT/path);assert sha==item['SHA256']
            ledgers[path]=value;refs[path]=sha;counts['選抜実台帳読取']+=1
        return ledgers[path]
    for session in sorted({v['選抜']['session'] for v in choices},key=result['sessions'].index):
        packet,sha=tools.read(tools.ROOT/meta['cache'][session]['path'])
        assert sha==meta['cache'][session]['SHA256'];refs[meta['cache'][session]['path']]=sha
        counts['選抜場cache読取']+=1
        for selection in (v for v in choices if v['選抜']['session']==session):
            chosen=selection['選抜'];symbol=chosen['symbol'];mode=chosen['mode'];id=chosen['id']
            account=packet['accounts'][symbol];key=session+'|'+symbol
            ni=[i for i in result['results'][id]['ledgers'] if i['session']==session and i['symbol']==symbol];assert len(ni)==1
            fresh=load(ni[0]);b8=load(fixed['bindings'][mode]['P1L8']['ledgers'][key]);b4=load(fixed['bindings'][mode]['P1L4']['ledgers'][key])
            independent=tools.contribution(b8,fresh)
            for f in FIELDS:assert np.isclose(independent[f],chosen['diff'][f],atol=1e-5,rtol=0.)
            a,b=tools.parents(b8),tools.parents(fresh)
            if 'parent' in chosen:cid=int(chosen['parent'])
            elif selection['種類']=='旧勝ち親が消えた利益喪失最大例':
                cid=max((c for c in a.keys()-b.keys() if a[c]['収支']>0),key=lambda c:a[c]['収支'])
            else:
                cid=max(a.keys()&b.keys(),key=lambda c:b[c]['収支']-a[c]['収支'])
            window=next(c['window_seconds'] for c in result['configs'] if c['id']==id)
            control=fresh.get('control',{});decision=control.get('判断行')
            entry=int(a[cid]['新規行']);decision_info=snapshot(account,b8,decision,window) if decision is not None else None
            record=dict(種類=selection['種類'],id=id,mode=mode,symbol=symbol,session=session,固定対象親=cid,
                場全体比較=dict(基準P1L8=b8['summary'],基準P1L4=b4['summary'],新政策=fresh['summary']),
                二対照5寄与=dict(P1L8=independent,P1L4=tools.contribution(b4,fresh)),
                新政策判断=control,判断時基準の実残玉情報=decision_info,
                基準P1L8親=parent_detail(b8,account,cid,window),
                新政策親=parent_detail(fresh,account,cid,window) if cid in b else None,
                同じ親の実収支差=b[cid]['収支']-a[cid]['収支'] if cid in b else None,
                同親を救った意味='基準の負けが軽減した例でも新政策が黒字になったとは限らない。場停止は後続取引も変える。',
                時計='JST日付はepochの実日本日付を保持。Night名前の日付へ丸めない。')
            records.append(clean(record))
        del packet;gc.collect()
    counter=[]
    for config in result['configs']:
        id=config['id'];mode=config['mode'];diffs=result['各場寄与'][id]['P1L8']
        for symbol in ('TOPIX','NK225'):
            ds=[d for d in diffs if d['symbol']==symbol]
            fired=[d for d in ds if d['control'].get('種別')=='逆票かつ4呼値損失']
            oldrows=[r for r in fixed['bindings'][mode]['P1L8']['rows'] if r['symbol']==symbol]
            counter.append(dict(id=id,symbol=symbol,基準P1L8収支=sum(r['収支'] for r in oldrows),
                新収支=result['results'][id]['symbols'][symbol]['収支'],
                追加条件発動場=len(fired),全場分母=33,
                追加条件発動のうち改善場=sum(d['収支変化']>0 for d in fired),
                追加条件発動のうち悪化場=sum(d['収支変化']<0 for d in fired),
                判定分母='逆票かつ4呼値損失が初先着で発火したセッション。非発火を成功へ含めない。',
                基準黒字親分母=sum(r['勝ち親'] for r in oldrows),
                基準黒字親の赤字化=sum(len(d['元勝ち親が赤字化']) for d in ds),
                全二対照5寄与={name:values[symbol] for name,values in result['diagnosis'][id].items()}))
    assert counts['選抜実台帳読取']<396
    output=dict(全合格=True,正式出典='00103',選抜計画SHA256=plansha,金融結果SHA256=resultsha,
        固定SHA256=fixedsha,特徴目録SHA256=metasha,具体例=records,
        該当例なし=[v for v in plan['選抜'] if v['選抜'] is None],全6の改善頻度と勝ち喪失反証=counter,
        読取件数=dict(counts),資料SHA256=refs,
        結論=['追加逆票退出が両銘柄で有効とは言えない。全6が両商品同時黒字を満たさない。',
            'CONFIRM NK W30/W60は価格のみP1L4より黒字を回復したが、旧P1L8+23280円よりそれぞれ12780/10780円悪化。',
            '逆票と一時損失は継続逆行の証拠にも、一時押し戻しの証拠にもなった。4呼値での返済確定が回復を逃す反例がある。',
            '追加条件は損失が発生した場を軽減しても、基準勝ち親の途中撤退や後続勝ち親消失を生む。場全体と親差を分ける。'],
        限界=['診断例は実測最大の事後選抜。これ自体は当時に勝ち負けを予測する法則ではない。',
            '票は公表出来高増行の最終価格方向代理。真の買売出来高/攻撃注文量ではない。',
            '事後最大清算時価は実現可能な別出口収益ではない。新規金融再生なし。',
            'P1L8は追加退出なし、P1L4は価格損失だけ。逆票だけの保有中退出は今回未測定。'],
        新金融=0,元paper再生=0,原NPZ=0,原book=0,API=0)
    sha=tools.write('全6二対照の具体損失軽減と勝ち喪失の診断.json',clean(output))
    print('具体subset診断保存',sha,dict(counts),flush=True)
    for r in records:
        print(r['種類'],r['symbol'],r['mode'],r['session'],r['固定対象親'],r['二対照5寄与']['P1L8']['収支変化'],flush=True)


if __name__=='__main__':main()
