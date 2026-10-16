"""同一初回からの追加床と継続保有の違いを、原本照合した暗色SVGへ描く。"""

from pathlib import Path
import hashlib
import importlib.util
import json
import pickle
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REPORT = HERE.parent / 'report'
JST = ZoneInfo('Asia/Tokyo')
sys.dont_write_bytecode = True


def load_module():
    """
    機能: 既存の入力読取・原本照合・描画間引きだけを再利用する。
    引数: なし。
    返り値: 旧ケース描画のモジュール(module)。旧mainは実行しない。
    """
    spec = importlib.util.spec_from_file_location('wave87_allocation_case_helper', REPORT / 'cases.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def clock(timestamp):
    """
    機能: 保存の代理時計を日本時間で短く表示する。
    引数: timestamp(float)。
    返り値: str の時分秒。
    """
    return datetime.fromtimestamp(float(timestamp), JST).strftime('%H:%M:%S')


def render(symbol, ready, base, added, helper, ledger_hashes):
    """
    機能: 第2親の価格・追加・合算床・両方式返済を二段図へ描く。
    引数: symbol(str)、ready/base/added(dict)、helper(module)、ledger_hashes(dict)。
    返り値: dict の原本照合と図指紋。売買再生や条件選抜は行わない。
    """
    cid = 1
    b = base['orders'][base['orders'][:, 2] == cid]
    a = added['orders'][added['orders'][:, 2] == cid]
    np.testing.assert_array_equal(b[0], a[0])
    assert len(b) == 3 and len(a) == 6
    assert all(a[3:, 6] == 76) and len(set(a[3:, 0])) == 1
    events = added['allocation_events']
    floors = events[(events[:, 1] == cid) & (events[:, 2] == 3)]
    assert len(floors) == 2
    entry, add1, add2, close = a[:4]
    partial, final = b[1:]
    orders = [entry, add1, add2, close, partial, final]
    times, prices, seq = ready['time_s'], ready['last'], ready['seq']
    rows = [int(o[0]) for o in orders]
    first, last = rows[0], rows[-1]
    for order in orders:
        assert order[5] == prices[int(order[0])]
        assert int(order[1]) < int(order[0])
    assert all(int(f[0]) in rows for f in floors)
    requested = {int(seq[i])+1: {'価格': float(prices[i]), '時計': float(times[i])} for i in rows}
    for order in orders:
        i = int(order[1])
        requested[int(seq[i])+1] = {'価格': float(prices[i]), '時計': float(times[i])}
    raw_path = ROOT / 'book' / symbol / '2026-09-28_Day.jsonl'
    raw_checks = helper.raw_markers(raw_path, requested)
    net_base = sum(float(t['収支']) for t in base['net_trades'] if t['組'] == cid)
    net_added = sum(float(t['収支']) for t in added['net_trades'] if t['組'] == cid)
    all_qty = int(np.sum(a[a[:, 7] == 1, 4]))
    unit = 'pt' if symbol == 'TOPIX' else '円'
    nick = 'TOPIX' if symbol == 'TOPIX' else '日経225'
    identifier = 'topix' if symbol == 'TOPIX' else 'nk225'
    fmt = ',.1f' if symbol == 'TOPIX' else ',.0f'
    captions = ['共通の初回売り', '追加① 売り', '追加② 売り', '合算床で全玉返済', '追加なし：途中半減', '追加なし：残り返済']
    colors = ['#e2e8f0', '#c4b5fd', '#a78bfa', '#fb7185', '#2dd4bf', '#34d399']
    metadata = {
        '内容': '追加後の床が初回玉も閉じた具体例。未来の価格経路と最終収支は事後診断。',
        'セッション': '2026-09-28_Day', '商品': symbol, '親組': cid,
        'モデル': '観測CurrentPrice、指定線モデルや売買気配モデルと混合しない',
        '比較': ['A_S2', 'A_D05_R'], '初回注文完全一致': True,
        '収支円': {'A_S2': net_base, 'A_D05_R': net_added},
        '床設定': [{'保存行': int(f[0]), '原本行': int(seq[int(f[0])])+1,
                    '時刻': clock(times[int(f[0])]), '床価格': float(f[6]),
                    '有効開始保存行': int(f[0])+1} for f in floors],
        'マーカー': [{'番号': j+1, '内容': captions[j], '保存行': i, '原本行': int(seq[i])+1,
                      '根拠保存行': int(o[1]), '根拠原本行': int(seq[int(o[1])])+1,
                      '価格': float(o[5]), '数量': all_qty if j == 3 else int(o[4]),
                      '時刻': clock(times[i])} for j, (i, o) in enumerate(zip(rows, orders))],
        '原本直接照合': raw_checks, '原本SHA256': helper.sha(raw_path),
        '台帳SHA256': ledger_hashes,
        '限定': '事後説明用に選んだ一組。全セッション収支ではない。保存観測間の真の価格順序・受信時計・ミニ/マイクロ同価格約定は保証しない。',
    }
    # ----------------------------------------
    # 上段は元玉終了までの全経路、下段は初回から30分に固定した拡大。床は設定後だけ表示する。
    plt.rcParams.update({'font.family': 'Yu Gothic', 'font.size': 11, 'svg.fonttype': 'path',
                         'axes.unicode_minus': False, 'savefig.facecolor': '#101827'})
    fig = plt.figure(figsize=(13.5, 10.8), dpi=125, facecolor='#101827')
    full = fig.add_axes((.085, .602, .86, .23), facecolor='#0b1220')
    zoom = fig.add_axes((.085, .317, .86, .211), facecolor='#0b1220')
    for panel, end_time in ((full, times[last]+45), (zoom, times[first]+1800)):
        lo = max(0, int(np.searchsorted(times, times[first]-45, side='left')))
        hi = min(len(times), int(np.searchsorted(times, end_time, side='right')))
        idx = np.arange(lo, hi)
        idx = idx[np.isfinite(prices[idx]) & (prices[idx] > 0)]
        essential = [int(np.searchsorted(idx, i)) for i in rows if lo <= i < hi]
        compact = helper.compact(times[idx], prices[idx], essential, columns=1050)
        x = np.asarray([datetime.fromtimestamp(float(t), JST) for t in times[idx]])
        panel.plot(x[compact], prices[idx][compact], color='#a9bed3', linewidth=1.15, zorder=2)
        for k, f in enumerate(floors):
            begin = int(f[0])+1
            end = int(floors[k+1, 0]) if k+1 < len(floors) else rows[3]
            if begin <= end:
                panel.plot([datetime.fromtimestamp(float(times[begin]), JST), datetime.fromtimestamp(float(times[end]), JST)],
                           [f[6], f[6]], color='#fbbf24', linewidth=1.6, linestyle=(0, (5, 3)), zorder=4)
        close_dt = datetime.fromtimestamp(float(times[rows[3]]), JST)
        panel.axvline(close_dt, color='#fb7185', alpha=.6, linewidth=1)
        if panel is full:
            panel.axvspan(close_dt, datetime.fromtimestamp(float(end_time), JST), color='#264260', alpha=.19, zorder=0)
        visible = range(6) if panel is zoom else (0, 3, 4, 5)
        for j in visible:
            i, o = rows[j], orders[j]
            if times[i] > end_time:
                continue
            xx = datetime.fromtimestamp(float(times[i]), JST)
            panel.scatter(xx, o[5], s=66 if j == 3 else 45, color=colors[j],
                          marker='X' if j == 3 else ('v' if j < 3 else '^'),
                          edgecolor='#0b1220', linewidth=.65, zorder=6)
            offset = (7, 12)
            if j == 0: offset = (7, -21)
            if j == 3: offset = (9, 10)
            if j == 5: offset = (-19, 12)
            panel.annotate(str(j+1), (xx, o[5]), xytext=offset, textcoords='offset points',
                           color=colors[j], fontsize=12, weight='bold',
                           bbox=dict(boxstyle='round,pad=.13', facecolor='#101827', edgecolor='none', alpha=.9))
        lows = list(prices[idx]) + [float(f[6]) for f in floors]
        spread = max(lows)-min(lows)
        pad = max(float(ready['tick'])*2, spread*.12)
        panel.set_ylim(min(lows)-pad, max(lows)+pad)
        panel.set_xlim(datetime.fromtimestamp(float(times[first]-45), JST), datetime.fromtimestamp(float(end_time), JST))
        panel.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8, tz=JST))
        panel.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=JST))
        panel.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter('{x:'+fmt+'}'))
        panel.tick_params(colors='#afc0d2', labelsize=10)
        panel.grid(color='#263446', linewidth=.6)
        panel.set_ylabel('ラージ現在値（'+unit+'）', color='#cbd5e1', fontsize=10)
        for spine in panel.spines.values():
            spine.set_color('#334155')
    # ----------------------------------------
    # 短い説明と正確な売買時刻を図の外へ揃え、価格線との重なりを避ける。
    fig.text(.085, .958, f'{nick}  2026/09/28 デイ ｜ 追加後の床が初回玉まで返済', color='#f8fafc', size=18, weight='bold')
    fig.text(.085, .922, '同じ売りから開始。追加後の小さな戻りで全玉を閉じ、その後の下落を取れなかった。', color='#d4e1ed', size=12)
    fig.text(.085, .884, f'この親組の料金後収支：追加なし A_S2  {net_base:+,.0f}円', color='#34d399', size=12, weight='bold')
    fig.text(.55, .884, f'段階追加 A_D05_R  {net_added:+,.0f}円', color='#fb7185', size=12, weight='bold')
    fig.text(.085, .85, '全体：共通の初回から、追加なし方式の最終返済まで', color='#cbd5e1', size=11)
    fig.text(.505, .85, '赤い線より右の値動き・最終収支は事後診断', color='#93a9bf', size=10)
    fig.text(.085, .55, '拡大：初回から30分 ｜ 紫＝追加、黄色破線＝全玉の損失を制限する床', color='#cbd5e1', size=11)
    for j, (i, o) in enumerate(zip(rows, orders)):
        col, line = j % 3, j // 3
        px, py = .085+col*.30, .255-line*.074
        qty = all_qty if j == 3 else int(o[4])
        fig.text(px, py, f'{j+1}  {captions[j]}  {clock(times[i])}', color=colors[j], size=10.5, weight='bold')
        fig.text(px, py-.025, f'{format(float(o[5]), fmt)} {unit}  ／  {qty}枚', color='#e2e8f0', size=11)
    floor_values = ' → '.join(format(float(f[6]), fmt) for f in floors)
    fig.text(.085, .108, f'床の更新：{floor_values} {unit}。指定線は追加約定後に設定し、次の保存観測から有効。', color='#fbbf24', size=10)
    fig.text(.085, .079, '原本行（①→⑥）：'+' / '.join(str(int(seq[i])+1) for i in rows)+'。各売買と根拠行の時刻・現在値を原板で直接照合。', color='#91a5bb', size=8.7)
    fig.text(.085, .053, '追加方式では初回玉は利益中でも、後から建てた玉の損失と合算して全返済した。事後の下落を当時予知できたという意味ではない。', color='#afc0d2', size=9)
    fig.text(.085, .026, '観測CurrentPriceによる仮想約定。時計はCurrentPriceTime。保存間の経路・真の受信時刻・ミニ／マイクロの約定を保証しない。', color='#91a5bb', size=8.5)
    path = REPORT / f'case_allocation_{identifier}_20260928.svg'
    preview = HERE / f'case_allocation_{identifier}_20260928_preview.png'
    fig.savefig(path, format='svg', metadata={'Title': f'{nick}の段階追加と合算床の具体例',
        'Description': json.dumps(metadata, ensure_ascii=False, separators=(',', ':')), 'Date': None})
    fig.savefig(preview, dpi=125)
    plt.close(fig)
    return dict(図=str(path.relative_to(ROOT)), SHA256=helper.sha(path), 原本照合件数=len(raw_checks),
                収支円=metadata['収支円'], 床=metadata['床設定'], マーカー=metadata['マーカー'], 表示確認=str(preview))


def main():
    """
    機能: 保存台帳から指定二口座のSVGだけをreportへ新規保存する。
    引数: なし。
    返り値: None。他のreportファイル、売買実装、既存台帳は変更しない。
    """
    helper = load_module()
    inputs = helper.load_inputs()
    sources = {name: ROOT / f'work/wave_v87/round6/observed/ledgers/{name}.pkl' for name in ('A_S2', 'A_D05_R')}
    accounts = {name: pickle.loads(path.read_bytes()) for name, path in sources.items()}
    hashes = {str(path.relative_to(ROOT)): helper.sha(path) for path in sources.values()}
    for name, path in sources.items():
        expected = json.loads((path.parent.parent / 'results' / f'{name}.json').read_text(encoding='utf-8'))
        assert hashes[str(path.relative_to(ROOT))] == expected['ledger_SHA256']
    results = []
    for symbol in ('TOPIX', 'NK225'):
        key = ('2026-09-28_Day', symbol)
        results.append(render(symbol, inputs[key], accounts['A_S2'][key], accounts['A_D05_R'][key], helper, hashes))
    (HERE / '追加床図の原本照合.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()
