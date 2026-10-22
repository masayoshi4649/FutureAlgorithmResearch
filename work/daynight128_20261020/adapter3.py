"""日中の原Ｅ０１通知と、昼夜の円会計を接続する。"""

import numpy as np
import day_core2
import night3


def day_filter(feed, ready, market, history, kind):
    """
    機能: 既存ＧＱ通知の発注判断行で、今回の日中追加条件を判定する。
    引数: feed/market/history(ndarray)、ready(dict)、kind(int)は追加条件。
    返り値: ndarrayは採用親の通知。後続原行の価格を採否に使用しない。
    """
    take, accepted = [], {}
    for i, order in enumerate(feed):
        row, parent, side = int(order[0]), int(order[2]), int(order[3])
        if order[7] == 1.:
            ok = True
            if kind in (1, 2, 3):
                known = market[row,11] == 1. and np.isfinite(market[row,4:8]).all()
                if kind in (1, 3):
                    ok = known and not (side*market[row,5] < -.1 and side*market[row,7] < -.1)
                elif kind == 2:
                    ok = known and side*market[row,4] > .05 and side*market[row,6] > .05
                if kind == 3:
                    ok = ok and ready["time_s"][row] >= ready["start"]+1800.
            elif kind == 4:
                ok = np.isfinite(history[row]).all()
                ok = ok and side*(ready["last"][row]-history[row,8]) > 0. and side*history[row,13] > 0.
            elif kind == 5:
                ok = market[row,11] == 1. and np.isfinite(market[row,4]) and np.isfinite(market[row,6])
                ok = ok and side*market[row,4] >= -.05 and side*market[row,6] >= -.05
            accepted[parent] = ok
        if accepted[parent]:
            take.append(i)
    return feed[take].copy()



def resize_feed(feed, market, weak_fraction):
    """
    機能: 発注判断時の短期支持が弱い親の数量を落とし、紙上部分返済も同じ比率へ対応する。
    引数: feed/market(ndarray)、weak_fraction(float)は採用通知・当時の二市場・弱い時の比率。
    返り値: ndarrayは整数枚数通知。部分返済の累計を最寄り整数へ丸め、最終全量を保存する。
    """
    result, state = [], {}
    for order in feed:
        row,parent,side = int(order[0]),int(order[2]),int(order[3])
        if order[7] == 1.:
            strong = market[row,11] == 1. and np.isfinite(market[row,4]) and np.isfinite(market[row,6])
            strong = strong and side*market[row,4] > .05 and side*market[row,6] > .05
            original = int(order[4])
            desired = original if strong else max(1,int(round(original*weak_fraction)))
            state[parent] = [original,desired,0,0]
            take = desired
        else:
            current=state[parent]
            current[2] += int(order[4])
            target = int(np.floor(current[2]*current[1]/current[0]+.5))
            take = target-current[3]
            current[3] = target
        if take:
            changed=order.copy()
            changed[4]=take
            result.append(changed)
    return np.asarray(result).reshape((-1,10))


def play_day(config, ready, quotes, market, history, feed):
    """
    機能: 採用通知を既存気配数値核と日中出口へ渡す。
    引数: config/ready/quotes(dict)、market/history/feed(ndarray)。
    返り値: dictは注文・返済脚・親・全行時価・状態。費用は別途注文別に積む。
    """
    accepted = day_filter(feed, ready, market, history, config["entry_filter"])
    accepted = resize_feed(accepted,market,config["weak_fraction"])
    values = day_core2.simulate(ready["time_s"], ready["last"], quotes["bid"], quotes["ask"],
        quotes["quote_valid"], accepted, ready["limit"], 10 if ready["symbol"] == "TOPIX" else 20,
        market, np.array([0.,.5,0.,0.,config["risk_floor"],config["protect_start"]]), ready["atr"], history, config["exit_rule"])
    names = ("orders","trades","curve","stats","cycles","order_uids",
             "execution_events","execution_states","actual_parents")
    return dict(zip(names, values))


def play_night(config, ready, quotes, market, history):
    """
    機能: 夜間新造の固定パラメータを注文状態機械へ渡す。
    引数: config/ready/quotes(dict)、market/history(ndarray)。
    返り値: dictは注文・完結取引・全行時価。
    """
    top = ready["symbol"] == "TOPIX"
    params = np.array([config[key] for key in ("mode","stop","trail_start","trail_width","phase",
        "cooldown","entry_bounce","opening_buffer","minimum_efficiency","band_distance",
        "entry_confirm","exit_mode","rearm","maximum_extension")], dtype=float)
    orders, trades, curve = night3.simulate(ready["time_s"], ready["last"],
        quotes["bid"],quotes["ask"],quotes["quote_valid"],ready["atr"],history,market,
        ready["start"],ready["limit"],ready["us_open"],ready["tick"],
        5 if top else 10, 1000. if top else 10.,418 if top else 110,params)
    return dict(orders=orders,trades=trades,curve=curve)


def summarize(result, ready, config):
    """
    機能: 新規と部分返済の注文別料金を積み、完結親単位の利益・損失を求める。
    引数: result/ready/config(dict)は完成配列、入力、条件。
    返り値: dictは一商品一場。利益玉だけの部分決済を勝ち件数に膨らませない。
    """
    top = ready["symbol"] == "TOPIX"
    mult, fee_tenths = (1000.,418) if top else (10.,110)
    orders = result["orders"]
    qty = orders[:,4].astype(np.int64)
    assert np.array_equal(qty, orders[:,4])
    order_fees = qty*fee_tenths//10
    entry = orders[:,7] == 1
    assert qty[entry].sum() == qty[~entry].sum()
    assert np.all(orders[:,0] > orders[:,1])
    fees = int(order_fees.sum())
    if config["engine"] == "day":
        cycles = result["cycles"]
        gross = cycles[:,3]*mult
        costs = np.array([order_fees[orders[:,2] == cycle[0]].sum() for cycle in cycles])
        nets = gross - costs
        assert np.isclose(gross.sum(),result["stats"][0]*mult)
        assert result["stats"][9] == 0
    else:
        gross, nets = result["trades"][:,6],result["trades"][:,8]
        assert np.isclose(nets.sum(), result["curve"][-1,0])
        assert result["curve"][-1,1] == 0
    assert np.isclose(gross.sum()-fees,nets.sum())
    return dict(method=config["id"],name=config["name"],kind=config["kind"],session=ready["session"],
        symbol=ready["symbol"],profit=float(nets[nets>0].sum()),loss=float(-nets[nets<0].sum()),
        net=float(nets.sum()),gross=float(gross.sum()),fees=fees,entries=int(entry.sum()),
        quantity=int(qty[entry].sum()),parent_wins=int((nets>0).sum()),parent_losses=int((nets<0).sum()),
        accounting="完結親単位の手数料後利益・損失",max_quantity=int(qty[entry].max()) if entry.any() else 0)
