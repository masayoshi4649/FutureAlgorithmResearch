"""既存50場の原入力と、手数料を売買経路からも外したTG04源を準備する。"""

from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'work/nikkei143_20261024'
sys.path.insert(0, str(OLD))
import common143 as shared
import profit_residual143 as residual
import episode143 as episode
import run143 as first143
import active_trader142 as active


def replay_active(data, config, fee10=0, original=False):
    """
    機能: 既存追加担当の内部会計も指定手数料で再生する。
    引数: data/config(dict)、fee10(int)は十倍手数料、original(bool)は旧A34源。
    返り値: ndarrayは次正常気配の全約定。金融再生は呼出者の登録後だけ行う。
    """
    r, q, c = data['ready'], data['quotes'], config
    args = (r['time_s'], q['bid'], q['ask'], q['quote_valid'], data['features'],
            r['start'], r['limit'], np.nan if r['session'].endswith('_Day') else r['us_open'],
            r['tick'], 100., fee10, c['mode'], c['initial'], c['maximum'], c['add_step'],
            c['stop'], c['activation'], c['trail'], c['hold'], c['cooldown'], c['ttl'],
            c['peer'], c['budget_ticks'], c['loss_pause'], c['loss_limit'], c['quiet_seconds'],
            r['limit'] - 600., 0.)
    if original:
        return shared.previous.first.original.simulate(*args)[0]
    return active.simulate(*args, c.get('entry_guard', 0), c.get('add_guard', 0),
                          c.get('exit_guard', 0), c.get('flow_guard', 0), c.get('evidence_hold', 15.),
                          c.get('partial_exit', False), c.get('entry_policy', 0),
                          c.get('management_policy', 0), c.get('add_policy', 0))[0]


def replay_episode(data, history, config, fee10=0):
    """
    機能: 別入口担当の費用連動床を含め、手数料指定で再生する。
    引数: data(dict)、history(ndarray)、config(dict)、fee10(int)。
    返り値: ndarrayは全約定。過去の費用列だけを書き換えた近似ではない。
    """
    r, q, c = data['ready'], data['quotes'], config
    keys = ('family', 'window', 'initial', 'maximum', 'partial', 'quiet_seconds', 'confirmation',
            'trend_confirmation', 'trail_range', 'activation_r', 'add_step', 'add_interval',
            'entry_cutoff', 'spread_range', 'min_range_ticks', 'gap_seconds')
    values = np.array([c[k] for k in keys], dtype=float)
    return episode.simulate(r['time_s'], q['bid'], q['ask'], q['quote_valid'], history,
        r['start'], r['limit'], np.nan if r['session'].endswith('_Day') else r['us_open'],
        r['tick'], fee10, values)[0]


def replay_residual(data, baseline, config, fee10=0):
    """
    機能: 既存H04と同じ残玉状態機械を、指定手数料の利益予算で再生する。
    引数: data(dict)、baseline(ndarray[N,10])、config(dict)、fee10(int)。
    返り値: tuple[ndarray,ndarray]は全約定と判断履歴。
    """
    baseline = np.asarray(baseline, dtype=float).reshape(-1, 10).copy()
    baseline[:, 9] = (baseline[:, 4] * fee10) // 10
    r, q = data['ready'], data['quotes']
    times = np.asarray(r['time_s'], dtype=float)
    if not len(baseline) or not config['enabled']:
        return baseline[baseline[:, 0] < len(times)], np.empty((0, len(residual.TRACE_COLUMNS)))
    bid, ask = np.asarray(q['bid']), np.asarray(q['ask'])
    good = np.asarray(q['quote_valid'], bool) & np.isfinite(bid) & np.isfinite(ask) & (bid > 0.) & (ask > bid)
    parents = list(dict.fromkeys(baseline[:, 2]))
    pmap = {p: i for i, p in enumerate(parents)}
    tickets = list(dict.fromkeys((row[2], row[8]) for row in baseline))
    tmap = {key: i for i, key in enumerate(tickets)}
    ep = np.array([pmap[row[2]] for row in baseline], np.int64)
    et = np.array([tmap[row[2], row[8]] for row in baseline], np.int64)
    tp = np.array([pmap[p] for p, _ in tickets], np.int64)
    tv = np.array([u for _, u in tickets], float)
    result, trace = residual._replay(times, bid, ask, good, np.asarray(r['atr']), float(r['tick']),
        float(r['limit']), float(r.get('us_open', np.nan)), baseline, ep, et,
        np.array(parents, float), tp, tv, np.array(config['eligible_reasons'], np.int64),
        float(config['trail_r']), float(config['profit_fraction']), float(config['quiet_seconds']), fee10, 100.)
    orders = result[np.lexsort((result[:, 10], result[:, 0])), :10] if len(result) else result[:, :10]
    return orders, trace


def prepare_scene(scene):
    """
    機能: 一場の費用0の基本・追加・別入口源とH04基準を準備する。
    引数: scene(str)は50既知場の識別名。
    返り値: tuple[dict,dict,dict,dict,dict]はpacket、data、元源、H04基準、事後評価ラベル。
    事前登録前は呼ばない。基本元通知は費用が判断に入らず、費用列のみ0とする。
    """
    packets, _, labels = shared.material()
    item = next(item for item in packets if item['session'] == scene)
    packet = shared.packet_from(item)
    prepared, _, _, history20 = shared.previous.prepared(packet)
    data = prepared['NK225']
    data['features'] = np.column_stack((data['features'], history20[scene, 'NK225'][:, 1]))
    day = scene.endswith('_Day')
    filename = OLD / ('round2' if day else 'round1') / 'measurement' / f'NK225_{scene}.npz'
    with np.load(filename) as archive:
        core = archive['O17' if day else 'O02'].copy()
    core[:, 9] = 0
    if day:
        config = dict(episode.configurations()[0], maximum=2, initial=2)
        history = active.history(data['ready']['time_s'], data['features'][:, 10], data['ready']['start'], 20)
        secondary = replay_episode(data, history, config)
    else:
        config = dict(shared.previous.first.original.configurations()[33], initial=1, maximum=2)
        secondary = replay_active(data, config, original=True)
    addon = replay_active(data, first143.addon_config(scene, 3))
    h04 = residual.configurations()[4]
    raw = {'CG': core, 'CS': secondary}
    baseline = {'CG04': replay_residual(data, core, h04)[0],
                'CS04': replay_residual(data, secondary, h04)[0], 'A3': addon}
    return packet, data, raw, baseline, labels[scene]
