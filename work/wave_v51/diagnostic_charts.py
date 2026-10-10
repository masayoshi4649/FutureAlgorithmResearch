"""連敗と仮想時計の待機を保存5分足と約定台帳から図示する。"""

import csv
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.font_manager import FontProperties


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'アルゴリズム調査/00048_E01連敗原因と再参加アルゴリズム'
JST = timezone(timedelta(hours=9))
FONT = FontProperties(fname='C:/Windows/Fonts/meiryo.ttc')
plt.rcParams.update({'font.family': FONT.get_name(), 'axes.unicode_minus': False})


def chart(session: str, start: str, end: str, title: str, shaded: tuple, caption: str, name: str) -> None:
    """機能: 保存5分足へE01の新規・返済と問題区間を重ねる。

    引数: session/start/end/title/caption/name(str)、shaded(tuple[str,str])。返り値: なし(None)。
    """
    with (ROOT / 'candle_5min/TOPIX' / (session + '.csv')).open(encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    lo, hi = datetime.fromisoformat(start), datetime.fromisoformat(end)
    fig, ax = plt.subplots(figsize=(12, 4.8), layout='constrained')
    fig.patch.set_facecolor('#0b121b')
    ax.set_facecolor('#101f30')
    ax.tick_params(colors='#bacbdd')
    for spine in ax.spines.values():
        spine.set_color('#40566e')
    ax.grid(color='#293e52', alpha=.6)
    for row in rows:
        stamp = datetime.fromisoformat(row['time'])
        if not lo <= stamp <= hi:
            continue
        x = mdates.date2num(stamp)
        op, close, high, low = (float(row[key]) for key in ('open', 'close', 'high', 'low'))
        color = '#7bdcb5' if close >= op else '#fa8f96'
        ax.vlines(x, low, high, color=color, linewidth=1)
        ax.add_patch(Rectangle((x - 1.8 / 1440, min(op, close)), 3.6 / 1440, max(.15, abs(close - op)), facecolor=color))
    ledgers = json.loads(gzip.decompress((ROOT / 'work/wave_v50/update_20261007_added/ledgers/E01.json.gz').read_bytes()))
    ledger = next(row for row in ledgers if row['session'] == session and row['symbol'] == 'TOPIX')
    import pickle
    inputs = pickle.loads((ROOT / 'work/wave_v50/update_20261007_added/new_inputs.pkl').read_bytes())
    ready = inputs[session, 'TOPIX']
    labels = set()
    for order in ledger['orders']:
        stamp = datetime.fromtimestamp(ready['time_s'][int(order[0])], JST)
        if not lo <= stamp <= hi:
            continue
        label = '買い新規' if order[7] == 1 and order[3] > 0 else '売り新規' if order[7] == 1 else '返済'
        marker, color = ('^', '#7ce4ff') if label == '買い新規' else ('v', '#ffe17a') if label == '売り新規' else ('x', '#ffffff')
        ax.scatter(stamp, order[5], marker=marker, color=color, s=65, linewidths=1.5, zorder=5, label=label if label not in labels else None)
        labels.add(label)
    ax.axvspan(datetime.fromisoformat(shaded[0]), datetime.fromisoformat(shaded[1]), color='#cf6d91', alpha=.13)
    ax.set_xlim(lo, hi)
    ax.set_title(title, color='#edf5ff', fontsize=14, loc='left', pad=13)
    ax.set_ylabel('TOPIX ラージ価格（pt）', color='#bacbdd')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=JST))
    ax.legend(facecolor='#172b40', edgecolor='#40566e', labelcolor='#e5eff8', loc='upper left', ncol=3)
    fig.text(.04, -.025, caption, color='#bacbdd', fontsize=10)
    for suffix in ('.png', '.svg'):
        fig.savefig(OUT / (name + suffix), dpi=140, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    """機能: 連敗夜間と再参加できなかった昼間の2図を保存する。

    引数: なし。返り値: なし(None)。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    chart('2026-10-05_Night', '2026-10-05T21:30:00+09:00', '2026-10-06T01:15:00+09:00',
          '10/05 ナイト：往復の中で新規を繰り返し、9連敗で −127,500円',
          ('2026-10-05T21:55:00+09:00', '2026-10-06T00:54:00+09:00'),
          '5分足とE01の実行済み注文。TOPIXミニ初回5枚換算。網掛けは9連敗の時間帯。', '連敗の価格経路')
    chart('2026-10-06_Day', '2026-10-06T11:30:00+09:00', '2026-10-06T15:40:00+09:00',
          '10/06 デイ：12:54の損切り後、15:35まで仮想時計が再参加を禁止',
          ('2026-10-06T12:54:39+09:00', '2026-10-06T15:35:00+09:00'),
          '網掛けは新規禁止区間。12:59には同方向信号が再発。事後の上昇幅は、実際に全て獲得できる利益とは異なります。', '再参加を阻んだ待機')


if __name__ == '__main__':
    main()
