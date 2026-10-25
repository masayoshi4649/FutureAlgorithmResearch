"""保存F1の夜上昇場を損失親の寄与で分解し、原文板へ接続する。新金融再生なし。"""

import json
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import common143 as common

sys.path.insert(0, str(common.ROOT / 'work/raw_diagnosis141_20261024'))
from supplement_loss_audit141 import parent_record, stamp
from loss_raw141 import clean

HERE, ROOT = common.HERE, common.ROOT


def plot_scene(scene, packet, history, records):
    """
    機能: 最大損失寄与場の二市場全景と最初二親の拡大価格を暗色で保存する。
    引数: scene(str)、packet/history(dict)、records(list[dict])は保存資料。
    返り値: strはPNGパス。高安・売買マーカーは事後の診断だけに用いる。
    """
    plt.rcParams['font.family'] = ['Yu Gothic', 'Meiryo', 'DejaVu Sans']
    fig, axes = plt.subplots(2, 2, figsize=(18, 9), sharex='col')
    fig.patch.set_facecolor('#0c1422')
    start = packet['inputs'][scene, 'NK225']['start']
    bounds = [(start, start + 780 * 60), (start + 345 * 60, start + 450 * 60)]
    for col, (begin, end) in enumerate(bounds):
        for row, symbol in enumerate(('NK225', 'TOPIX')):
            ax = axes[row, col]
            ax.set_facecolor('#101d30')
            ax.tick_params(colors='#dbe6f2')
            ax.grid(color='#33445e', alpha=.4)
            r = packet['inputs'][scene, symbol]
            q = packet['quotes'][scene, symbol]
            mask = q['quote_valid'] & (r['time_s'] >= begin) & (r['time_s'] <= end)
            times = r['time_s'][mask]
            mid = (q['bid'][mask] + q['ask'][mask]) * .5
            seconds = 60. if col == 0 else 10.
            bins = np.floor(times / seconds).astype(np.int64)
            first = np.r_[0, np.flatnonzero(np.diff(bins)) + 1]
            last = np.r_[first[1:] - 1, len(bins) - 1]
            x = bins[first] * seconds + seconds * .5
            ax.vlines(x, np.minimum.reduceat(mid, first), np.maximum.reduceat(mid, first),
                      color='#87b9e9', linewidth=.7)
            ax.plot(x, mid[last], color='#c1ddf8', lw=.8, label='高安を残した中値')
            ax.plot(times, history[scene, symbol][mask, 1], color='#efc56c', lw=.9, label='当時公開MA20')
            for p in records:
                first_order, last_order = p['orders'][0], p['orders'][-1]
                bt, et = first_order['fill_epoch'], last_order['fill_epoch']
                if et < begin or bt > end:
                    continue
                ax.axvspan(bt, et, color='#ff6981', alpha=.13)
                if symbol == 'NK225':
                    for o in p['orders']:
                        if begin <= o['fill_epoch'] <= end:
                            marker = ('^' if o['side'] > 0 else 'v') if o['new'] else 'x'
                            ax.scatter(o['fill_epoch'], o['price'], marker=marker, s=50,
                                       color='#ff8b9a' if o['new'] else '#f5f7fa', zorder=4)
                    ax.annotate(f'{p["role"]} {p["net"]:+,.0f}円', xy=(bt, first_order['price']),
                                xytext=(5, 12 + 13 * (p['parent'] % 2)), textcoords='offset points',
                                color='#ffd2da', fontsize=8)
            ax.set_xlim(begin, end)
            ax.xaxis.set_major_formatter(FuncFormatter(lambda t, _: stamp(t)[11:16]))
            ax.set_title(f'{symbol} / ' + ('全セッション' if col == 0 else '23時前後の拡大'), color='#e4edf7')
            ax.legend(facecolor='#17253a', edgecolor='#33445e', labelcolor='#dbe6f2', fontsize=8)
    fig.suptitle(f'F1 / {scene}：終了時は上昇、売り3親が赤字（価格時計・原板中値）',
                 color='#e4edf7', fontsize=15)
    fig.tight_layout(rect=(0, 0, 1, .95))
    target = HERE / '方向偏り_2026-10-15_Night.png'
    fig.savefig(target, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(target)


def main():
    """
    機能: 上昇夜の全親を再集計し、損失寄与上位三場だけ原文SHA付きで診断する。
    引数: なし。
    返り値: None。新規JSON・画像だけを保存し、売買エンジンは実行しない。
    """
    audit = common.read(HERE / 'F1始終値方向と深夜除外保有率143.json')
    rise = [x for x in audit['sessions'] if x['kind'] == 'Night' and x['direction'] == '上昇']
    ranked = sorted(rise, key=lambda x: -x['loss'])
    packets, caches, _ = common.material()
    source = {x['session']: x for x in packets}
    output = dict(金融再生=0, API取得=0, 対象='保存F1・日経mini・手数料後・夜上昇12場',
                  順位基準='完結赤字親の損失合計。黒字親で相殺した場収支順ではない。',
                  全体=audit['分類集計']['Night_上昇'],
                  比較夜下落=audit['分類集計']['Night_下落'],
                  全夜=[dict(session=x['session'], change=x['change'], profit=x['profit'],
                            loss=x['loss'], net=x['net'], parents=x['parents']) for x in ranked],
                  上位三場=[], 限界=['終値上昇は事後分類であり、入口時に知り得た情報ではない。',
                      '原資料の価格時計であり受信時計ではない。OFIは表示板の変化で参加者心理を断定しない。',
                      '原板はラージ先物BBO、損益はminiの倍率・手数料。mini自身の執行価格差は未測定。'])
    for scene_rank, label in enumerate(ranked[:3], 1):
        scene = label['session']
        packet = common.packet_from(source[scene])
        data, inputs, market, history = common.previous.prepared(packet)
        base, extra, f1 = common.sources(scene, caches)
        raw = {}
        for symbol in ('NK225', 'TOPIX'):
            with np.load(ROOT / 'work/raw_diagnosis141_20261024/raw_features' / f'{symbol}_{scene}.npz') as z:
                raw[symbol] = {k: z[k] for k in z.files}
        with np.load(common.OLD / 'traces' / f'NK225_{scene}.npz') as z:
            traces = z['C13']
        note = common.read(common.OLD / 'notes' / f'NK225_{scene}_Z04.json')
        k = scene, 'NK225'
        records = []
        for pid in sorted(np.unique(f1[:, 2]), key=lambda p: f1[f1[:, 2] == p][0, 0]):
            rows = f1[f1[:, 2] == pid]
            p = parent_record(rows, inputs[k], packet['quotes'][k], history[k], market[k],
                              raw['NK225'], inputs[scene, 'TOPIX'], raw['TOPIX'])
            role = next(x['role'] for x in label['parents'] if x['parent'] == pid)
            p['role'] = role
            p['gross'] = float(np.sum(-rows[:, 3] * rows[:, 4] * rows[:, 5] * 100.))
            p['fees'] = float(rows[:, 9].sum())
            p['entry_atr'] = float(inputs[k]['atr'][int(rows[0, 1])])
            p['selected_trace'] = []
            for t in traces:
                if role == '追加' and t[5] + 3000000 == pid:
                    i = int(t[0])
                    p['selected_trace'].append(dict(row=i, seq=int(inputs[k]['seq'][i]),
                        time=stamp(inputs[k]['time_s'][i]), event=int(t[1]), side=int(t[2]),
                        action=int(t[3]), reason=int(t[4]), gain_r=float(t[6]), best_r=float(t[7]),
                        failed_same=int(t[8]), features30=data['NK225']['features'][i]))
            for order in p['orders']:
                i = order['decision']['row']
                order['fill_epoch'] = float(inputs[k]['time_s'][order['fill_row']])
                order['decision']['public_atr'] = float(inputs[k]['atr'][i])
                order['decision']['own_ma5'] = float(history[k][i, 0])
                order['decision']['own_ma20'] = float(history[k][i, 1])
                order['decision']['features30'] = data['NK225']['features'][i]
                order['decision']['source_path'] = str(raw['NK225']['source_path'])
                order['decision']['source_line_sha256'] = raw['NK225']['line_sha256'][order['decision']['seq']].tobytes().hex()
                order['decision']['peer_source_path'] = str(raw['TOPIX']['source_path'])
            records.append(p)
        assert sum(p['net'] for p in records) == label['net']
        item = dict(rank=scene_rank, session=scene, change=label['change'], net=label['net'],
                    loss=label['loss'], profit=label['profit'], parents=records, Z04選択記録=note,
                    source_packet=source[scene])
        if scene_rank == 1:
            item['chart'] = plot_scene(scene, packet, history, records)
        output['上位三場'].append(item)
        print(scene, label['net'], flush=True)
        for p in records:
            print(p['role'], p['side'], p['net'], '最大順行', p['maximum_favorable_points'],
                  [(o['fill_time'][11:19], o['quantity'], o['price'], o['reason']) for o in p['orders']], flush=True)
    with (HERE / '方向偏りの損失原因143.json').open('x', encoding='utf-8') as f:
        json.dump(clean(output), f, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
