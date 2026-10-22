"""保存済み会計と注文を読み、追撃の具体的な失敗と勝ち反例を再集計する。金融再生はしない。"""

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import pickle
from statistics import median
import sys
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'work/staged137_20261022'))
from run137 import features129


def read(path):
    """
    機能: 保存済みJSONを読み取る。
    引数: path(Path)は対象。
    返り値: dict/listは内容。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stamp(value):
    """
    機能: 原行時刻を日本時間で表示する。
    引数: value(float)はUNIX秒。
    返り値: strは小数秒を残す日本時間。
    """
    return datetime.fromtimestamp(float(value), ZoneInfo('Asia/Tokyo')).isoformat(timespec='milliseconds')


def stats(rows):
    """
    機能: 会計を変更せず、場ごとの損失深度と大勝ち依存を集計する。
    引数: rows(list[dict])は同一商品・同一条件の保存済み行。
    返り値: dictは件数・収支・赤字統計・方向別収支。
    """
    nets = sorted(r['net'] for r in rows)
    losses = [-x for x in nets if x < 0]
    profits = [x for x in nets if x > 0]
    return dict(sessions=len(rows), winning=len(profits), losing=len(losses), flat=sum(x == 0 for x in nets),
                net=sum(nets), mean_loss=float(np.mean(losses)) if losses else 0., median_loss=float(median(losses)) if losses else 0.,
                max_loss=max(losses, default=0.), mean_win=float(np.mean(profits)) if profits else 0.,
                excluding_top3=sum(nets[:-3]), buy=sum(p['net'] for r in rows for p in r['parents'] if p['side'] == 1),
                sell=sum(p['net'] for r in rows for p in r['parents'] if p['side'] == -1),
                no_entry=sum(r['entries'] == 0 for r in rows))


def details(event, packet, market, order_file, all_rows):
    """
    機能: 最悪の追撃親について判断原行・約定・最高順行と比較親の収支を抽出する。
    引数: event/packet/market(dict)、order_file(Path)、all_rows(list[dict])は保存済み資料。
    返り値: dictは原板へ遡れる個別証跡。
    """
    scene, symbol, pid = event['session'], event['symbol'], event['parent']
    key = (scene, symbol)
    ready = packet['inputs'][key]
    quotes = packet['quotes'][key]
    times = ready['time_s']
    with np.load(order_file, allow_pickle=False) as saved:
        orders = saved['C04']
        orders = orders[orders[:, 2] == pid]
    first = orders[orders[:, 7] == 1][0]
    risk = max(20. if symbol == 'NK225' else 1., ready['atr'][int(first[1])])
    side = int(first[3])
    legs = []
    for uid in np.unique(orders[:, 8]):
        ticket = orders[orders[:, 8] == uid]
        initial = ticket[ticket[:, 7] == 1][0]
        closes = ticket[ticket[:, 7] == 0]
        start, finish = int(initial[0]), int(closes[-1, 1])
        rows = np.arange(start, finish + 1)
        good = quotes['quote_valid'][rows]
        mark = quotes['bid'][rows] if side > 0 else quotes['ask'][rows]
        move = side * (mark - initial[5])
        valid = good & np.isfinite(move)
        peak = float(np.max(move[valid])) if valid.any() else None
        feature = market[int(initial[1])]
        legs.append(dict(uid=int(uid), entry=stamp(times[int(initial[0])]), decision=stamp(times[int(initial[1])]),
                         entry_row=int(initial[0]), price=float(initial[5]), quantity=int(initial[4]),
                         decision_bid=float(quotes['bid'][int(initial[1])]), decision_ask=float(quotes['ask'][int(initial[1])]),
                         support=[float(side * feature[k]) for k in (4, 5, 6, 7)],
                         best_favorable_before_final_decision=peak,
                         best_favorable_R=peak / risk if peak is not None else None,
                         profit_activation=1.5 * risk if uid > 0 else None,
                         closes=[dict(time=stamp(times[int(o[0])]), decision=stamp(times[int(o[1])]),
                                      price=float(o[5]), quantity=int(o[4]), reason=int(o[6])) for o in closes]))
    alternatives = {}
    for method in ('B5', 'B2', 'C00', 'C01', 'C03', 'C04', 'P04', 'P07', 'C07', 'C12', 'C06', 'CN10', 'CN20'):
        match = next(r for r in all_rows if r['method'] == method and r['session'] == scene and r['symbol'] == symbol)
        parent = next((p for p in match['parents'] if p['id'] == pid), None)
        alternatives[method] = dict(session_net=match['net'], parent_net=parent['net'] if parent else None,
                                    added_net=sum(x['net'] for uid, x in parent['legs'].items() if uid not in ('0', '999')) if parent else None)
    return dict(event, side=side, initial_risk=risk, legs=legs, alternatives=alternatives)


def chart(packet, cache, scene, output):
    """
    機能: 保存原板から五分足を描き、C04の実保存注文だけを重ねる。
    引数: packet(dict)、cache(dict)、scene(str)、output(Path)は読み取り資料と画像出力先。
    返り値: None。損益計算・金融再生は行わない。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    plt.rcParams['font.family'] = ['Yu Gothic', 'Meiryo', 'DejaVu Sans']
    fig, axes = plt.subplots(2, 1, figsize=(15, 9), sharex=True, facecolor='#101820')
    for ax, symbol in zip(axes, ('NK225', 'TOPIX')):
        ready = packet['inputs'][(scene, symbol)]
        q = packet['quotes'][(scene, symbol)]
        times = ready['time_s']
        good = q['quote_valid'] & (times >= ready['start']) & (times <= ready['limit'])
        price = (q['bid'] + q['ask']) * .5
        slots = np.floor((times - ready['start']) / 300.).astype(np.int64)
        ax.set_facecolor('#15212b')
        for slot in np.unique(slots[good]):
            selected = np.flatnonzero(good & (slots == slot))
            values = price[selected]
            if not len(values):
                continue
            timestamp = datetime.fromtimestamp(float(ready['start'] + slot * 300. + 150.), ZoneInfo('Asia/Tokyo'))
            x = mdates.date2num(timestamp)
            color = '#61dcc3' if values[-1] >= values[0] else '#ff7c82'
            ax.vlines(x, values.min(), values.max(), color=color, linewidth=.8)
            height = max(abs(values[-1] - values[0]), ready['tick'] * .1)
            ax.add_patch(Rectangle((x - 100. / 86400., min(values[0], values[-1])), 200. / 86400., height, color=color, alpha=.8))
        with np.load(cache[(scene, symbol)], allow_pickle=False) as saved:
            orders = saved['C04']
        for o in orders:
            timestamp = datetime.fromtimestamp(float(times[int(o[0])]), ZoneInfo('Asia/Tokyo'))
            if o[7]:
                marker = '^' if o[3] > 0 else 'v'
                color = '#f3efb5' if o[8] == 0 else '#c493ff'
                ax.scatter(timestamp, o[5], marker=marker, color=color, s=55, zorder=5)
                ax.annotate(f"{int(o[4])}枚", (timestamp, o[5]), xytext=(3, 8), textcoords='offset points', color=color, fontsize=8)
            else:
                ax.scatter(timestamp, o[5], marker='x', color='#ffffff', s=30, zorder=5)
        ax.set_title(f'{symbol}：確定5分足・C04の保存注文', color='#e5edf5', loc='left')
        ax.grid(color='#30404d', alpha=.5)
        ax.tick_params(colors='#c7d5e3')
        for spine in ax.spines.values():
            spine.set_color('#415365')
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=ZoneInfo('Asia/Tokyo')))
    fig.suptitle(f'{scene}  初回＝黄色／追撃＝紫／返済＝白×（事後全経路図）', color='#e5edf5')
    fig.tight_layout()
    fig.savefig(output, dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    """
    機能: 主比較の保存済み47場から、三大追撃損失と改善・反例の資料を作る。
    引数: なし。
    返り値: None。元入力・会計・注文は変更しない。
    """
    rows = []
    cache = {}
    for name in ('results', 'extra_results'):
        saved = read(HERE / name / '結果.json')
        rows.extend(dict(r, sample='追加2' if name == 'extra_results' else '既知45') for r in saved['rows'])
        for item in saved['cache']:
            cache[(item['session'], item['symbol'])] = ROOT / item['path']
    primary = ('B5', 'C04', 'P07', 'C12', 'C06', 'CN20')
    summaries = []
    for sample in ('全47', '既知45', '追加2'):
        for symbol in ('NK225', 'TOPIX'):
            for method in primary:
                selected = [r for r in rows if r['symbol'] == symbol and r['method'] == method and (sample == '全47' or r['sample'] == sample)]
                summaries.append(dict(sample=sample, symbol=symbol, method=method, **stats(selected)))
    events = []
    for symbol in ('NK225', 'TOPIX'):
        bad = []
        for r in rows:
            if r['symbol'] == symbol and r['method'] == 'C04':
                for parent in r['parents']:
                    added = sum(x['net'] for uid, x in parent['legs'].items() if uid not in ('0', '999'))
                    if added < 0:
                        bad.append(dict(symbol=symbol, session=r['session'], parent=parent['id'], added_net=added,
                                        parent_net=parent['net'], initial_net=parent['legs'].get('0', {}).get('net', 0.)))
        events.extend(sorted(bad, key=lambda x: x['added_net'])[:3])
    manifests = read(HERE / 'manifest139.json')['packets'] + read(HERE / 'manifest139_extra.json')['packets']
    observations = []
    details_out = []
    figures = []
    figure_scenes = ('2026-10-20_Day', '2026-10-08_Day', '2026-10-15_Day')
    for item in manifests:
        scene = item['session']
        packet = pickle.loads(Path(item['path']).read_bytes())
        for symbol in ('NK225', 'TOPIX'):
            ready = packet['inputs'][(scene, symbol)]
            q = packet['quotes'][(scene, symbol)]
            ts = ready['time_s']
            good = q['quote_valid'] & (ts >= ready['start']) & (ts <= ready['limit'])
            indices = np.flatnonzero(good)
            prices = (q['bid'][indices] + q['ask'][indices]) * .5
            movement = float(prices[-1] - prices[0])
            observations.append(dict(session=scene, symbol=symbol, move=movement, direction='上昇' if movement > 0 else '下落' if movement < 0 else '横ばい'))
        selected_events = [e for e in events if e['session'] == scene]
        if selected_events:
            markets = features129.markets(features129.prices_for(packet, 'mid'))
            for event in selected_events:
                details_out.append(details(event, packet, markets[(scene, event['symbol'])], cache[(scene, event['symbol'])], rows))
        if scene in figure_scenes:
            target = HERE / ('診断_' + scene + '.png')
            chart(packet, cache, scene, target)
            figures.append(target.relative_to(ROOT).as_posix())
        print(scene + ' 保存資料確認', flush=True)
    regimes = []
    for symbol in ('NK225', 'TOPIX'):
        for method in primary:
            for direction in ('上昇', '下落', '横ばい'):
                scenes = {x['session'] for x in observations if x['symbol'] == symbol and x['direction'] == direction}
                selected = [r for r in rows if r['method'] == method and r['symbol'] == symbol and r['session'] in scenes]
                if selected:
                    regimes.append(dict(symbol=symbol, method=method, direction=direction, **stats(selected)))
    pair_deltas = []
    for symbol in ('NK225', 'TOPIX'):
        for baseline, candidate in (('C03', 'C04'), ('C04', 'C06'), ('P04', 'P07'), ('C04', 'C12'), ('CN10', 'CN20')):
            old = {r['session']: r for r in rows if r['method'] == baseline and r['symbol'] == symbol}
            new = [r for r in rows if r['method'] == candidate and r['symbol'] == symbol]
            deltas = [dict(session=r['session'], before=old[r['session']]['net'], after=r['net'], difference=r['net'] - old[r['session']]['net']) for r in new]
            pair_deltas.append(dict(symbol=symbol, baseline=baseline, candidate=candidate,
                                   total=sum(x['difference'] for x in deltas), rescued=sum(x['before'] < 0 <= x['after'] for x in deltas),
                                   spoiled=sum(x['before'] >= 0 > x['after'] for x in deltas),
                                   best=sorted(deltas, key=lambda x: -x['difference'])[:3],
                                   worst=sorted(deltas, key=lambda x: x['difference'])[:3]))
    source_paths = [HERE / 'results/結果.json', HERE / 'extra_results/結果.json', Path(__file__).resolve()]
    insights = [
        'C04の追撃損失最大6親・追撃15玉は最高順行がすべて0～0.96Rで、1.5R起動へ未到達。起動後の幅短縮ではこの損失を防げない。',
        '2026-10-20日経は初回2枚の売り・買いが共に黒字でも、遅れて増やした玉が親の反転返済まで残り親全体を赤字化した。支持は当時成立していたが持続を保証しなかった。',
        '次に分離して測るべき因子は、後段ほど利益保護の起動水準も下げること、または親の部分返済でどの玉を残すかである。今回の保存結果だけでは優位性未確認。',
        '追撃間隔拡大は日経の負け深度を抑える例がある一方、2026-09-29の継続下落利益を減らした。全場一律の正解にはなっていない。',
        '初回の部分利確を待つC06はTOPIXの合計を増やしたが、日経2026-10-16日中を-72,914円から-150,916円へ悪化させた。様子見の全廃や全面拡張を支持しない。',
        '日経C04の上昇場は22場中11赤字、下落場は25場中7赤字。売買式は対称でも実績は下落場へ偏る。両方向安定の完成とは呼べない。',
        '画像は10月20日の往復、10月8日の朝の下落終了、10月15日の長い下落を確認した事後図であり、その形を未来の入口へ直接流用していない。',
    ]
    output = dict(再集計のみ=True, 金融再生=0, 所見=insights, 概要=summaries, 上昇下落別=regimes, 価格区分=observations,
                  追撃最大損失=details_out, 因子差分=pair_deltas, 画像=figures,
                  出典={p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in source_paths})
    (HERE / '保存結果の独立診断.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    lines = ['# 保存済み結果の独立診断', '', '新しい金融再生は行っていない。既知45場と固定追加2場、計47場の保存会計を再集計した。', '',
             '## 原因と修正候補', '', *['- ' + x for x in insights], '',
             '| 商品 | 条件 | 収支 | 赤字場 | 平均赤字 | 中央赤字 | 最大赤字 | 上位3黒字場除外 |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summaries:
        if s['sample'] == '全47':
            lines.append(f"| {s['symbol']} | {s['method']} | {s['net']:+,.0f} | {s['losing']}/47 | {s['mean_loss']:,.0f} | {s['median_loss']:,.0f} | {s['max_loss']:,.0f} | {s['excluding_top3']:+,.0f} |")
    lines += ['', '## 追撃部分の最大損失各3件', '', 'C04の追撃玉だけの手数料後損益で順位を付けた。初回減枚と出口変更が混ざるB5との差を、そのまま追撃の因果効果と呼ばない。', '']
    for event in details_out:
        lines += [f"### {event['symbol']} {event['session']} 親{event['parent']}", '',
                  f"初回 {event['initial_net']:+,.0f}円、追撃 {event['added_net']:+,.0f}円、親合計 {event['parent_net']:+,.0f}円。初回固定R={event['initial_risk']:.3f}。", '',
                  '| 玉 | 新規時刻 | 方向 | 値段 | 枚数 | 最高順行/R | 返済 |', '|---|---|---|---:|---:|---:|---|']
        for leg in event['legs']:
            closes = ' / '.join(f"{x['time'][11:23]} {x['price']:g}×{x['quantity']}枚" for x in leg['closes'])
            lines.append(f"| {leg['uid']} | {leg['entry'][11:23]} | {'買' if event['side'] > 0 else '売'} | {leg['price']:g} | {leg['quantity']} | {leg['best_favorable_R']:.2f} | {closes} |")
        lines += ['', '比較親損益：' + '、'.join(f"{method} {v['parent_net']:+,.0f}円" if v['parent_net'] is not None else f'{method} 見送り' for method, v in event['alternatives'].items()), '']
    lines += ['## 因子別の改善と勝ち反例', '']
    for item in pair_deltas:
        lines += [f"- {item['symbol']} {item['baseline']}→{item['candidate']}：差額{item['total']:+,.0f}円、赤字→非赤字{item['rescued']}場、非赤字→赤字{item['spoiled']}場。"]
        for label in ('best', 'worst'):
            example = item[label][0]
            lines += [f"  - {'最大改善' if label == 'best' else '最大悪化'}：{example['session']} {example['before']:+,.0f}→{example['after']:+,.0f}円。"]
    lines += ['', '## 限界', '', '- 上昇・下落区分は事後の始値終値差による診断であり、入口選択には用いない。',
              '- 上位候補の結果を見た後の既知データ診断であり、将来の優位性の独立証明ではない。',
              '- 二市場支持は追加時に成立していたことと、その後順行が続くことは別の事象。',
              '- 追加の利益追尾は追加自身が1.5R進むまで起動しない。初回の含み益を追撃の利益として流用していない。',
              '- 金額の市場間大小は倍率差を含むため直接優劣としない。', '']
    (HERE / '保存結果の独立診断.md').write_text('\n'.join(lines), encoding='utf-8')
    print('保存済み会計の診断完了', flush=True)


if __name__ == '__main__':
    main()
