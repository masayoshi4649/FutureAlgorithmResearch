"""強度だけの変更を、失う旧勝敗・代替新規・ATRと呼値の構成変化へ分解する。"""

from collections import defaultdict
import math
import pickle
import numpy as np

from accounts import ROOT, WORK, HERE, read, digest, save


def quantiles(values):
    """
    機能: 事前に定めた四分位と両端寄りの分位で分布を要約する。
    引数: values (iterable[float])。
    返り値: dict又はNone の10/25/50/75/90百分位。
    """
    values = [float(value) for value in values if math.isfinite(value)]
    return dict(zip(('p10','p25','p50','p75','p90'),map(float,np.quantile(values,(.1,.25,.5,.75,.9))))) if values else None


def amounts(values):
    """
    機能: 親組の勝敗と料金前後を商品内だけで合算する。
    引数: values (iterable[dict])。
    返り値: dict の会計。
    """
    values = list(values)
    profit = math.fsum(max(0,v['net']) for v in values)
    loss = math.fsum(max(0,-v['net']) for v in values)
    wins = sum(v['net'] > 0 for v in values)
    losses = sum(v['net'] < 0 for v in values)
    return dict(組数=len(values),利益=profit,損失=loss,収支=profit-loss,
                手数料=math.fsum(v['fee'] for v in values),粗損益=math.fsum(v['gross'] for v in values),
                勝組=wins,負組=losses,勝率=wins/len(values) if values else None,
                金額利益割合=profit/(profit+loss) if profit+loss else None,
                平均勝負比=(profit/wins)/(loss/losses) if wins and losses else None)


def classify_atr(value):
    """
    機能: ATRを呼値数へ直した量を共通の粗い固定区間へ分類する。
    引数: value (float) はATR/呼値。
    返り値: str の区間名。結果に合わせて境界を変更しない。
    """
    return '4呼値未満' if value < 4 else '4以上8未満' if value < 8 else '8以上16未満' if value < 16 else '16以上'


def records(ledgers, inputs, shorts, models):
    """
    機能: 旧新の親組を同じ入口行・方向へ対応し、その直前に既知の強度も保存する。
    引数: ledgers/inputs/shorts/models (dict) は保存台帳・原値・公開支持。
    返り値: dict[tuple,dict] の入口別明細。将来損益は事後値として分離する。
    """
    output = {}
    for key, ledger in ledgers.items():
        ready, short = inputs[key],shorts[key]
        grouped = defaultdict(list)
        for trade in ledger['net_trades']:
            grouped[int(trade['組'])].append(trade)
        cycles = {int(c[0]):c for c in ledger['cycles']}
        preparations = {int(p[0]):int(p[3]) for p in ledger['entry_preparations']}
        for order in ledger['orders'][ledger['orders'][:,7] == 1]:
            entry, cid, side = int(order[0]),int(order[2]),int(order[3])
            legs = grouped[cid]
            previous = entry-1
            atr, tick = float(cycles[cid][5]),float(ready['tick'])
            event = int(short['self_event_index'][previous])
            current_atr = float(models[key]['atr'][event])
            own = side*float(short['self_value'][previous])
            peer = side*float(short['peer_value'][previous])
            index = (key[0],key[1],entry,side)
            assert index not in output
            output[index] = dict(cid=cid,entry=entry,side=side,exit=max(int(t['返済行']) for t in legs),
                net=math.fsum(t['収支'] for t in legs),fee=math.fsum(t['手数料'] for t in legs),
                gross=math.fsum(t['利益損失前'] for t in legs),entry_price=float(order[5]),
                initial_atr=atr,initial_atr_ticks=atr/tick,current_atr=current_atr,
                current_atr_ticks=current_atr/tick,own=own,peer=peer,
                own_valid=bool(short['self_valid'][previous]),peer_valid=bool(short['peer_valid'][previous]),
                move_ticks=own*current_atr/tick,
                fees_to_R=math.fsum(t['手数料'] for t in legs)/(atr*float(order[4])*(1000 if key[1] == 'TOPIX' else 10)),
                time=legs[0]['新規時刻'],raw_row=int(ready['seq'][entry])+1,
                prepare_row=preparations[cid],entry_time=float(ready['time_s'][entry]),tick=tick)
    return output


def passes(row, config):
    """
    機能: 旧入口直前の元公開値だけで、新しい閾値も成立していたか確認する。
    引数: row/config (dict)。
    返り値: bool。別経路で実際に注文できたことを意味しない。
    """
    value = row['own_valid'] and row['own'] > config['threshold_atr']
    if config['support_mode'] == 3:
        value = value and row['peer_valid'] and row['peer'] > config['threshold_atr']
    return bool(value)


def distribution(rows):
    """
    機能: 最新支持の値動き部分とATR分母・費用の構成を分ける。
    引数: rows (iterable[dict])。
    返り値: dict の過去特徴分布と事後会計。
    """
    rows = list(rows)
    return dict(既存親組会計_事後=amounts(rows),
                初期ATR呼値数_過去=quantiles(r['initial_atr_ticks'] for r in rows),
                支持計算ATR呼値数_過去=quantiles(r['current_atr_ticks'] for r in rows),
                支持方向中値差呼値数_過去=quantiles(r['move_ticks'] for r in rows),
                自己支持ATR比_過去=quantiles(r['own'] for r in rows),
                料金対初期R比_事後=quantiles(r['fees_to_R'] for r in rows),
                同じ初期ATR帯={band:amounts(r for r in rows if classify_atr(r['initial_atr_ticks']) == band)
                            for band in ('4呼値未満','4以上8未満','8以上16未満','16以上')})


def compare(old, new, config):
    """
    機能: 同行同方向・旧入口消失・新入口追加へ収支差を恒等的に分解する。
    引数: old/new/config (dict)。
    返り値: dict の対応分解と構成変化。
    """
    common = old.keys() & new.keys()
    removed = old.keys() - new.keys()
    added = new.keys() - old.keys()
    old_same,new_same = amounts(old[k] for k in common),amounts(new[k] for k in common)
    gone,extra = amounts(old[k] for k in removed),amounts(new[k] for k in added)
    delta = {name:new_same[name]-old_same[name] for name in ('粗損益','手数料','収支')}
    old_all,new_all = amounts(old.values()),amounts(new.values())
    for field in delta:
        assert abs(new_all[field]-old_all[field]-(delta[field]-gone[field]+extra[field])) < 1e-6
    old_prep = {(k[0],k[1],v['prepare_row'],v['side']):v for k,v in old.items()}
    new_prep = {(k[0],k[1],v['prepare_row'],v['side']):v for k,v in new.items()}
    assert len(old_prep) == len(old) and len(new_prep) == len(new)
    matching = sorted(old_prep.keys() & new_prep.keys())
    later = [(old_prep[k],new_prep[k]) for k in matching if old_prep[k]['entry'] != new_prep[k]['entry']]
    adverse = [a['side']*(b['entry_price']-a['entry_price'])/a['tick'] for a,b in later]
    waits = [b['entry_time']-a['entry_time'] for a,b in later]
    return dict(元全組=old_all,新全組=new_all,収支差=new_all['収支']-old_all['収支'],
                同行同方向の元=old_same,同行同方向の新=new_same,同行同方向の差=delta,
                同行でも初期ATRが違う組=sum(old[k]['initial_atr'] != new[k]['initial_atr'] for k in common),
                同行でも建値が違う組=sum(old[k]['entry_price'] != new[k]['entry_price'] for k in common),
                消えた旧入口=gone,代替の新入口=extra,
                失った旧勝ち=amounts(old[k] for k in removed if old[k]['net'] > 0),
                減った旧負け=amounts(old[k] for k in removed if old[k]['net'] < 0),
                消えた旧入口で新閾値も不成立=amounts(old[k] for k in removed if not passes(old[k],config)),
                消えた旧入口だが新閾値は成立=amounts(old[k] for k in removed if passes(old[k],config)),
                同じ準備からの注文タイミング変化=dict(対応組数=len(matching),約定行変更組数=len(later),
                    元より不利価格=sum(value > 1e-9 for value in adverse),元より有利価格=sum(value < -1e-9 for value in adverse),
                    同価格=sum(abs(value) <= 1e-9 for value in adverse),不利方向価格差呼値=quantiles(adverse),
                    新規時刻の追加秒=quantiles(waits),
                    注記='同じセッション・商品・準備行・方向に限定した比較。後の準備が変わる全入口の代表ではない。'),
                元の入口構成=distribution(old.values()),新しい入口構成=distribution(new.values()),
                注記='消失は閾値による直接見送りだけでなく、先行の保有や影時計・準備変更を含む。同じ入口行でも初期ATRや再公開の指定価格が異なる場合がある。')


def main():
    """
    機能: 固定十二条件を同じ親方式・同じ市場条件のH005だけと全期間対応比較する。
    引数: なし。
    返り値: None。全比較JSONを保存し、結果から新しい閾値は選ばない。
    """
    fixed = read(WORK/'事前固定.json')
    proof = read(ROOT/'work/wave_v85/prepared/入力準備の完了.json')
    inputs = {}
    for item in proof['入力対応']:
        path = ROOT/item['inputs']
        assert digest(path) == proof['使用入力SHA256'][item['inputs']]
        inputs.update(pickle.loads(path.read_bytes()))
    support_path = WORK.parent/'round3/prepared/short.pkl'
    assert digest(support_path) == read(support_path.with_name('支持準備の照合.json'))['出力SHA256']
    support = pickle.loads(support_path.read_bytes())
    all_models = {}
    fingerprints = {}
    for model in fixed['models']:
        packets,groups = {},{}
        for config in fixed['catalog']:
            path = WORK/model/'results'/f"{config['id']}.json"
            packet = read(path)
            ledger_path = WORK/model/'ledgers'/f"{config['id']}.pkl"
            assert digest(ledger_path) == packet['ledger_SHA256']
            assert packet['config'] == config
            fingerprints[str(path.relative_to(ROOT))] = digest(path)
            packets[config['id']] = packet
            groups[config['id']] = records(pickle.loads(ledger_path.read_bytes()),inputs,support['expanded'],support['events'])
        summaries = []
        for config in fixed['catalog']:
            identifier = config['id']
            baseline = config['round3_id']+'_H005'
            periods = {}
            for period in ('前16','後14','全30'):
                products = {}
                for symbol in ('TOPIX','NK225'):
                    old = {k:v for k,v in groups[baseline].items() if k[0] in fixed[period] and k[1] == symbol}
                    new = {k:v for k,v in groups[identifier].items() if k[0] in fixed[period] and k[1] == symbol}
                    result = compare(old,new,config)
                    actual = packets[identifier]['periods'][period][symbol]
                    assert abs(result['新全組']['収支']-actual['net']) < 1e-6
                    assert result['新全組']['組数'] == actual['campaigns']
                    result['全戦略評価'] = {name:actual[name] for name in
                        ('net','campaign_profit','campaign_loss','campaign_profit_share','campaign_payoff',
                         'campaigns','campaign_wins','campaign_losses','positive_sessions','negative_sessions',
                         'no_trade_sessions','max_drawdown','worst_session','best_session_removed','fees')}
                    result['日夜'] = {label:amounts(v for k,v in new.items() if k[0].endswith(label)) for label in ('Day','Night')}
                    products[symbol] = result
                periods[period] = products
            summaries.append(dict(条件=identifier,対照=baseline,固定主=identifier == 'GU_F1_H025',期間別=periods))
        all_models[model] = summaries
        print(model,'十二条件の失った勝ち・代替入口・ATR呼値構成を照合',flush=True)
    save('全12強度条件の入口変更とATR呼値構成の独立分解.json',dict(
        全合格=True,固定主='GU_F1_H025',主の差替え=False,新しい閾値選抜=False,
        モデル別=all_models,保存結果SHA256=fingerprints,
        制約=['旧入口の消失額だけを改善額としない。同行差・消失・追加の合計が全収支差と一致する。',
              '支持比が大きいのは価格変化増だけでなくATR低下も含む。呼値数と固定ATR帯を併記するが、因果を断定しない。',
              '観測モデルの約定は保存CurrentPrice。売買気配差や真の受信時刻の再現ではない。',
              '全30も前16/後14も既知。条件付き関連を未知期間の予測確率と呼ばない。']))


if __name__ == '__main__':
    main()
