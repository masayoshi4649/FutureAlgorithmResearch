"""追加赤字の代表二例を、保存価格と既知の注文線で暗色SVGへ描く。"""

import hashlib
import importlib.util
import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
JST = ZoneInfo('Asia/Tokyo')
sys.dont_write_bytecode = True


def read(path):
    """
    機能: 日本語JSONを読み込む。
    引数: path (Path) は対象資料。
    返り値: dict又はlist の保存値。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: ファイルの内容指紋を求める。
    引数: path (Path) は対象資料。
    返り値: str のSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs():
    """
    機能: 保存済み全30場の元E01入力を指紋照合して読み込む。
    引数: なし。
    返り値: dict の口座別入力。売買再生は行わない。
    """
    spec = importlib.util.spec_from_file_location('wave87_case_prepare', ROOT / 'work/wave_v85/prepare.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    inputs, _, _ = module.load_inputs(verify=True)
    return inputs


def compact(time, price, required, columns=1000):
    """
    機能: 横幅ごとの先頭・末尾・高安を時系列順に残して図を軽くする。
    引数: time/price (ndarray)、required (list[int])、columns (int)。
    返り値: ndarray[int] の残す位置。同時計の価格差も保持する。
    """
    groups = np.floor((time-time[0])/max(1., time[-1]-time[0])*columns).astype(int)
    boundaries = np.r_[0, np.flatnonzero(np.diff(groups))+1, len(time)]
    keep = set(required)
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        local = price[start:end]
        keep.update((int(start), int(end-1), int(start+np.argmin(local)), int(start+np.argmax(local))))
    return np.asarray(sorted(keep), dtype=int)


def raw_markers(path, requested):
    """
    機能: 売買マーカーの原本行にある現在値と時計を直接照合する。
    引数: path (Path)、requested (dict[int,dict]) は1始まり原本行と期待値。
    返り値: list[dict] の原本照合証跡。
    """
    found = []
    with path.open(encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            if number not in requested:
                continue
            raw = json.loads(line)
            raw = raw.get('data', raw)
            expected = requested[number]
            assert float(raw['CurrentPrice']) == expected['価格'], (path, number)
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == expected['時計'], (path, number)
            found.append(dict(原本1始まり行=number, 現在値=raw['CurrentPrice'], 時計=raw['CurrentPriceTime']))
            if len(found) == len(requested):
                break
    assert len(found) == len(requested)
    return found


def render(case, account, data):
    """
    機能: 前玉返済から再参加・初期損切りまでを一枚のSVGへ描く。
    引数: case/account/data (dict) は監査例・台帳・保存入力。
    返り値: dict の図・短文・根拠情報。
    """
    cid = case['親組']
    cycle = next(c for c in account['cycles'] if int(c[0]) == cid)
    prior = next(c for c in account['cycles'] if int(c[0]) == cid-1)
    start, end = int(cycle[1]), int(cycle[2])
    prior_start, prior_end = int(prior[1]), int(prior[2])
    current_orders = account['orders'][account['orders'][:, 2] == cid]
    previous_orders = account['orders'][(account['orders'][:, 2] == cid-1) & (account['orders'][:, 7] == 0)]
    entry = current_orders[current_orders[:, 7] == 1][0]
    exit_order = current_orders[current_orders[:, 7] == 0][-1]
    previous_order = previous_orders[-1]
    prices, times, seq = data['last'], data['time_s'], data['seq']
    assert int(entry[0]) == start and int(exit_order[0]) == end
    assert int(previous_order[0]) == prior_end
    assert int(seq[start])+1 == case['原本1始まり行']
    assert float(entry[5]) == case['建値'] and float(exit_order[5]) == case['全返済価格']
    assert float(previous_order[5]) == case['前回全返済価格']
    previous_prices = prices[prior_start:prior_end+1]
    assert float(np.max(previous_prices)) == case['前回高値']
    assert float(np.min(previous_prices)) == case['前回安値']
    forward = prices[start:end+1]-float(entry[5])
    assert max(0., float(np.max(forward))) == case['最大順行']
    assert max(0., float(-np.min(forward))) == case['最大不利']
    net = sum(t['収支'] for t in account['net_trades'] if t['組'] == cid)
    assert abs(net-case['収支']) < 1e-8
    # ----------------------------------------
    # 過去に終了済みの前玉高値は前玉返済時からだけ描き、今の停止線は新規以降だけ描く。
    begin = max(prior_start, int(np.searchsorted(times, times[prior_end]-180., side='left')))
    finish = min(len(times)-1, int(np.searchsorted(times, times[end]+45., side='right'))-1)
    indices = np.arange(begin, finish+1)
    valid = np.isfinite(prices[indices]) & (prices[indices] > 0)
    indices = indices[valid]
    p, t = prices[indices], times[indices]
    essential = [int(np.flatnonzero(indices == i)[0]) for i in (prior_end, start, end)]
    selection = compact(t, p, essential)
    x = mdates.date2num([datetime.fromtimestamp(float(v), JST) for v in t])
    markx = {i: mdates.date2num(datetime.fromtimestamp(float(times[i]), JST)) for i in (prior_end, start, end)}
    symbol = case['商品']
    nick = 'TOPIX' if symbol == 'TOPIX' else '日経225'
    identifier = 'topix_20260925' if symbol == 'TOPIX' else 'nk225_20260922'
    brief = ('前の高値へ届かないまま、115秒後に再び買い。' if symbol == 'TOPIX' else
             '前の高値を30円更新して買っても、次の順行はなかった。')
    caption = ('新しいEMA足を読んでも、小反発の再参加が有利とは限らない。' if symbol == 'TOPIX' else
               '高値更新とEMA再同調だけでは、この失敗を除外できない。')
    unit = 'pt' if symbol == 'TOPIX' else '円'
    plt.rcParams.update({'font.family': 'Yu Gothic', 'font.size': 11, 'svg.fonttype': 'path',
                         'axes.unicode_minus': False, 'savefig.facecolor': '#111827'})
    fig = plt.figure(figsize=(12, 7), dpi=140, facecolor='#111827')
    ax = fig.add_axes((.085, .32, .86, .47), facecolor='#0b1220')
    ax.plot(x[selection], p[selection], color='#9fbcdb', linewidth=1.2, zorder=3)
    ax.axvspan(markx[start], markx[end], color='#164e63', alpha=.18, zorder=0)
    ax.hlines(case['前回高値'], markx[prior_end], x[-1], color='#fbbf24', linestyle=(0, (5, 4)), linewidth=1.2, zorder=2)
    ax.hlines(case['初期損切り指定線'], markx[start], x[-1], color='#f87171', linestyle=(0, (5, 4)), linewidth=1.3, zorder=2)
    ax.hlines(case['建値'], markx[start], markx[end], color='#34d399', linestyle=(0, (2, 4)), linewidth=1, alpha=.75, zorder=2)
    plotted = list(p)+[case['前回高値'], case['初期損切り指定線']]
    low, high = min(plotted), max(plotted)
    gap = max(float(data['tick']), (high-low)*.13)
    ax.set_ylim(low-gap, high+gap)
    ax.set_xlim(x[0], x[-1])
    ax.tick_params(colors='#b6c5d5', labelsize=10)
    ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter('{x:,.1f}' if symbol == 'TOPIX' else '{x:,.0f}'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=7, tz=JST))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=JST))
    ax.grid(color='#263446', linewidth=.65)
    for spine in ax.spines.values():
        spine.set_color('#334155')
    ax.set_ylabel('保存されたラージ現在値（'+unit+'）', color='#cbd5e1', labelpad=9)
    markers = []
    for number, i, order, color, description in (
        (1, prior_end, previous_order, '#fbbf24', '前玉返済'),
        (2, start, entry, '#34d399', '買い直し'),
        (3, end, exit_order, '#f87171', '初期損切り')):
        price = float(order[5])
        ax.axvline(markx[i], color=color, linewidth=.9, alpha=.52, zorder=1)
        ax.scatter([markx[i]], [price], color=color, s=52, edgecolor='#0b1220', linewidth=1, zorder=5)
        offset = (7, 12) if number != 1 else (-15, -20)
        ax.annotate(str(number), (markx[i], price), xytext=offset, textcoords='offset points',
                    color=color, weight='bold', fontsize=12,
                    bbox=dict(boxstyle='round,pad=.13', facecolor='#111827', edgecolor='none'))
        stamp = datetime.fromtimestamp(float(times[i]), JST).strftime('%H:%M:%S')
        markers.append(dict(番号=number, 内容=description, 保存行=i, 原本1始まり行=int(seq[i])+1,
                            発注根拠保存行=int(order[1]), 発注根拠原本1始まり行=int(seq[int(order[1])])+1,
                            時刻=stamp, 時計=float(times[i]), 価格=price, 枚数=int(order[4])))
        px = .085+(number-1)*.30
        fig.text(px, .255, f'{number}  {description}  {stamp}', color=color, fontsize=11, weight='bold')
        fig.text(px, .212, f'{price:,.1f} {unit}  ／  {int(order[4])}枚', color='#e2e8f0', fontsize=11)
    fig.text(.085, .95, f'{nick}  {case["セッション"].replace("_Day", " デイ").replace("_Night", " ナイト")}',
             color='#f8fafc', fontsize=17, weight='bold')
    fig.text(.085, .902, brief, color='#d4e1ed', fontsize=12)
    fig.text(.085, .838, f'前玉の高値 {case["前回高値"]:,.1f} {unit}（前玉返済時までに既知）', color='#fbbf24', fontsize=10)
    fig.text(.525, .838, f'新規後の停止指定線 {case["初期損切り指定線"]:,.1f} {unit}', color='#f87171', fontsize=10)
    fig.text(.085, .152, f'料金後収支 {net:+,.0f}円  ｜  事後診断：最大順行 +{case["最大順行"]:g}{unit}、最大逆行 −{case["最大不利"]:g}{unit}',
             color='#e2e8f0', fontsize=11)
    fig.text(.085, .111, caption, color='#b8c7d7', fontsize=10)
    fig.text(.085, .064, '原本行（1→3）：'+ ' ／ '.join(str(m['原本1始まり行']) for m in markers)+
             '。発注根拠の原本行：'+ ' ／ '.join(str(m['発注根拠原本1始まり行']) for m in markers)+
             '。最大順行・逆行は事後診断。', color='#8ca0b6', fontsize=8.5)
    fig.text(.085, .033, '保存価格のスナップショット。時計はCurrentPriceTime。ミニ／マイクロの同価格約定や真の受信時刻を保証しない。',
             color='#8ca0b6', fontsize=8.5)
    svg = HERE / ('case_'+identifier+'.svg')
    png = HERE / ('case_'+identifier+'_preview.png')
    fig.savefig(svg, format='svg', metadata={'Title': brief, 'Description': caption, 'Date': None})
    fig.savefig(png, dpi=140)
    plt.close(fig)
    requested = {m['原本1始まり行']:m for m in markers}
    checks = raw_markers(ROOT / 'book' / symbol / (case['セッション']+'.jsonl'), requested)
    return dict(id=identifier, title=f'{nick}：'+brief, caption=caption, svg=svg.name, preview=png.name,
                svg_SHA256=sha(svg), 例=case, マーカー=markers, 原本直接照合=checks,
                表示窓=dict(開始=datetime.fromtimestamp(float(t[0]), JST).isoformat(),
                            終了=datetime.fromtimestamp(float(t[-1]), JST).isoformat(),
                            原価格観測数=len(t), 描画点数=len(selection)),
                過去に既知=['前玉が終わるまでの高値', '実新規後に設定した停止指定線'],
                事後診断=['当該保有区間の最大順行・最大逆行', 'この取引の最終損益'],
                注記='最悪例を選んだ原因説明。高値更新の有無だけで将来勝率を推定しない。')


def main():
    """
    機能: 指定二例の暗色SVG・表示確認PNG・連携JSONを作る。
    引数: なし。
    返り値: None。公開フォルダや既存成果は変更しない。
    """
    proof = WORK / 'audit/独立原因監査の結論.json'
    source = read(proof)
    selected = [next(r for r in source['代表6例'] if r['商品'] == symbol and r['セッション'] == session)
                for symbol, session in [('TOPIX', '2026-09-25_Day'), ('NK225', '2026-09-22_Night')]]
    ledgerpath = ROOT / 'work/wave_v86/phase2/observed/ledgers/T2_P1.pkl'
    result = read(ledgerpath.parent.parent / 'results/T2_P1.json')
    assert sha(ledgerpath) == result['ledger_SHA256']
    with ledgerpath.open('rb') as stream:
        ledgers = pickle.load(stream)
    inputs = load_inputs()
    cases = [render(case, ledgers[case['セッション'], case['商品']], inputs[case['セッション'], case['商品']])
             for case in selected]
    value = dict(手法='T2_P1', 約定モデル='観測現在値', 新PL再生=False,
                 全図の台帳価格時刻原本一致=True,
                 原資料SHA256={str(proof.relative_to(ROOT)): sha(proof), str(ledgerpath.relative_to(ROOT)): sha(ledgerpath)},
                 cases=cases)
    (HERE / 'cases.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({r['id']:r['svg_SHA256'] for r in cases}, ensure_ascii=False))


if __name__ == '__main__':
    main()
