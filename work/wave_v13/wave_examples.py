"""ユーザーが事前に指定した４つの波と、固定主候補の保有区間を照合する。"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


OUT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
WINDOWS = [
    ('2026-09-21_Day', '2026-09-21T10:45:00+09:00', '2026-09-21T15:35:00+09:00', 1),
    ('2026-09-22_Day', '2026-09-22T09:20:00+09:00', '2026-09-22T11:45:00+09:00', -1),
    ('2026-09-22_Night', '2026-09-23T00:40:00+09:00', '2026-09-23T03:20:00+09:00', 1),
    ('2026-09-23_Day', '2026-09-23T09:05:00+09:00', '2026-09-23T11:15:00+09:00', -1),
]


def clock_text(value: float) -> str:
    """機能: 原本の時刻を日本時間の短い文字列へ変換する。

    引数: value (float) は秒単位の時刻。返り値: 日付と時分秒 (str)。
    """
    return datetime.fromtimestamp(value, JST).strftime('%m/%d %H:%M:%S')


def main() -> None:
    """機能: 既存の固定主候補の全取引から、指定方向で重なる保有だけを数える。

    引数: なし。返り値: None。条件の再選択・新規通信・再学習は行わない。
    """
    trades = json.loads((OUT/'学習代表_全取引.json').read_text(encoding='utf-8'))
    selection = json.loads((OUT/'最終選択.json').read_text(encoding='utf-8'))
    rows = []
    details = []
    for symbol, record in selection['主候補'].items():
        candidate = record['採用']['方式']
        for session, left, right, direction in WINDOWS:
            start, end = datetime.fromisoformat(left).timestamp(), datetime.fromisoformat(right).timestamp()
            matching = [t for t in trades if t['銘柄'] == symbol and t['方式'] == candidate
                        and t['セッション'] == session and t['方向'] == direction
                        and t['新規時刻'] < end and t['返済評価時刻'] > start]
            intervals = sorted((max(start, t['新規時刻']), min(end, t['返済評価時刻'])) for t in matching)
            merged = []
            for a, b in intervals:
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            minutes = sum(b-a for a,b in merged)/60
            row = dict(銘柄=symbol, 方式=candidate, セッション=session, 指定開始=left, 指定終了=right,
                       指定方向='ロング' if direction > 0 else 'ショート',
                       同方向保有分=minutes, 指定区間内保有割合=minutes/((end-start)/60),
                       該当脚数=len(matching), 該当脚の最終収支円=sum(t['収支円'] for t in matching))
            rows.append(row)
            details.extend(dict(指定波=f'{session} {left[11:16]}〜{right[11:16]}', **t) for t in matching)

    # ----------------------------------------
    (OUT/'指定した４波の照合.json').write_text(json.dumps(dict(
        用途='条件固定後の説明用。波の時間・方向はユーザーの過去指示による。選択に戻さない。',
        注意='同方向保有割合は時間の重なりであり、値幅捕捉率・予測正答率ではない。最終収支は該当脚の全保有期間で、指定窓外の損益も含む。',
        区間=rows, 該当売買=details), ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 指定した４つの波と固定主候補の照合', '',
             'ユーザーが以前指定した時間帯・方向に対し、固定主候補が実際に同方向の建玉を持った時間を確認した。9/21の「引けまで」は、この検証の強制返済開始15:35までとした。9/22ナイトの00:40は暦日9/23に属する。', '',
             '**保有割合は時間の重なりであり、値幅の捕捉率や予測正答率ではない。** 記載の収支は該当売買の全保有期間の最終収支で、窓外の損益を含む。条件選択・再調整には使用しない。', '',
             '| 銘柄 | セッション | 指定時刻・方向 | 同方向保有分 / 区間分 | 保有割合 | 該当脚数 | 該当脚の最終収支 |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        minutes = (datetime.fromisoformat(r['指定終了'])-datetime.fromisoformat(r['指定開始'])).total_seconds()/60
        lines.append(f"| {r['銘柄']} | {r['セッション']} | {r['指定開始'][11:16]}〜{r['指定終了'][11:16]} {r['指定方向']} | {r['同方向保有分']:.1f} / {minutes:.0f} | {r['指定区間内保有割合']:.1%} | {r['該当脚数']} | {r['該当脚の最終収支円']/10000:+.1f}万円 |")
    lines += ['', '## 該当した売買の全時刻', '', '| 銘柄 | 方式 | 指定波 | 新規 | 返済 | 収支 |', '| --- | --- | --- | --- | --- | --- |']
    for t in details:
        lines.append(f"| {t['銘柄']} | {t['方式']} | {t['指定波']} | {clock_text(t['新規時刻'])} | {clock_text(t['返済評価時刻'])} | {t['収支円']/10000:+.1f}万円 |")
    lines += ['', '新規時刻が指定窓より早くても、窓内で同方向の保有が続いていれば含める。該当脚が０の窓は、方向検知の通知が一切ないことまでは意味せず、選択済みの入口・出口・待機条件でその波を売買できなかったことを示す。', '']
    (OUT/'指定した４波の照合.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
