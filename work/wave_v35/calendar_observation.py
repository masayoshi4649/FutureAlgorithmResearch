"""選択区間の暦の偏りと入力の観測量を、売買条件を変えず整理する。"""

from hashlib import sha256
import json
from pathlib import Path
import pickle
from statistics import median

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'wave_v23'


def main() -> None:
    """機能: 保存された26入力の記述統計と祝日区間の注意点を保存する。

    引数: なし。返り値: なし (None)。新しい売買再生・選択・現在取得は行わない。
    """
    inputs = pickle.loads((SOURCE / 'inputs.pkl').read_bytes())
    features = pickle.loads((SOURCE / 'features_depth.pkl').read_bytes())
    rows = []
    for (session, symbol), ready in sorted(inputs.items()):
        t, price = ready['time_s'], ready['last']
        use = (t >= ready['start']) & (t <= ready['limit'])
        t, price = t[use], price[use]
        assert len(t) > 1 and np.all(np.diff(t) >= 0)
        minutes = (t[-1] - t[0]) / 60
        bars = np.floor((t - ready['start']) / 300).astype(np.int64)
        endings = np.r_[np.flatnonzero(bars[1:] != bars[:-1]), len(bars) - 1]
        closes = price[endings]
        travel = float(np.abs(np.diff(closes)).sum())
        frame = features[(session, symbol)]
        frame = frame[(frame['time_s'] >= t[0]) & (frame['time_s'] <= t[-1])]
        classified_volume = frame[['trade_pos', 'trade_neg', 'trade_unknown']].sum().sum()
        rows.append(dict(セッション=session, 銘柄=symbol,
            区間='初期6' if session[:10] <= '2026-09-23' else '後7',
            時間帯=session.split('_')[1], 開始日は祝日=session[:10] <= '2026-09-23',
            観測分=float(minutes), 原本行数=len(t), 原本行毎分=len(t) / minutes,
            同一約定時刻隣接比=float(np.mean(np.diff(t) == 0)),
            解放板ブロック数=len(frame), 解放板毎分=len(frame) / minutes,
            板ブロック単純平均スプレッドtick=float(frame['spread_ticks'].mean()),
            推定約定数量毎分=float(classified_volume / minutes),
            始終差pt=float(price[-1] - price[0]), 範囲pt=float(np.ptp(price)),
            五分終値方向効率=float(abs(closes[-1] - closes[0]) / travel) if travel > 0 else 0.))
    fields = ['原本行毎分', '解放板毎分', '板ブロック単純平均スプレッドtick', '推定約定数量毎分', '五分終値方向効率']
    groups = []
    for symbol in ('TOPIX', 'NK225'):
        for period in ('Day', 'Night'):
            for span in ('初期6', '後7'):
                part = [r for r in rows if r['銘柄'] == symbol and r['時間帯'] == period and r['区間'] == span]
                groups.append(dict(銘柄=symbol, 時間帯=period, 区間=span, セッション数=len(part),
                    **{f: median(r[f] for r in part) for f in fields}))
    output = dict(用途='結果後の記述統計。休日を原因と断定せず、採否・条件・選択を変更しない。',
        公式確認='https://www.jpx.co.jp/news/2040/20260918-01.html',
        公式休業日='https://www.jpx.co.jp/corporate/about-jpx/calendar/',
        限界=['初期6の開始日は全て祝日。初期6は通常営業日のデイを含まない。',
            'ナイトはどちらの区間も日本の現物市場の営業時間外。開始日祝日の効果と同一視しない。',
            '原本行数は約定数でなく、CurrentPriceTimeは板の受信時刻ではない。',
            '推定約定数量は既存の分類列の合計。約定側・公式累計出来高の完全な再現ではない。',
            'スプレッドは解放板ブロック単純平均で、時間加重ではない。',
            '五分終値方向効率は区間終値差の絶対値/隣接終値差の絶対値合計。結果後の相場説明で入口には使えない。'],
        全入力=rows, 区分別中央値=groups,
        入力SHA256={p.name: sha256(p.read_bytes()).hexdigest() for p in (SOURCE / 'inputs.pkl', SOURCE / 'features_depth.pkl')},
        実装SHA256=sha256(Path(__file__).read_bytes()).hexdigest(), 売買再生=False, 採否変更=False)
    (HERE / '暦と観測量の点検.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    body = ['# 暦と観測量の点検', '',
        '**初期6の選択区間は9/21〜9/23の祝日開始セッションだけで、通常営業日のデイを含んでいなかった。**', '',
        '[JPXの実施通知](https://www.jpx.co.jp/news/2040/20260918-01.html)で3日とも祝日取引と確認した。これは選択用区間の偏りであり、「休日だから今回の差が生じた」という因果説明ではない。ナイトは全日とも日本の現物市場の営業時間外で、休日デイとは区別する。', '',
        '既知データからの結果後の点検である。暦を見て都合よく方式を変えたり、現在の選択・採否を変更したりしない。通常日と休日の双方を含む独立した将来データで初めて一般化を確かめられる。', '',
        '下表はセッション別測定値の中央値。板毎分は解放ブロック数、幅はブロック単純平均スプレッドtick、推定量は既存の約定分類数量/分、効率は5分終値の方向効率。', '',
        '| 銘柄 | 時間帯 | 区間 | 本数 | 板毎分 | 幅 | 推定量毎分 | 効率 |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    body += [f"| {r['銘柄']} | {r['時間帯']} | {r['区間']} | {r['セッション数']} | {r['解放板毎分']:.2f} | {r['板ブロック単純平均スプレッドtick']:.2f} | {r['推定約定数量毎分']:.2f} | {r['五分終値方向効率']:.3f} |" for r in groups]
    body += ['', '受信時刻と注文IDがなく、スナップショットの記録頻度と市場の実際の注文頻度は同じではない。数量分類にも欠測・推定が含まれる。原本26入力の測定と定義は [JSON](暦と観測量の点検.json) に保存した。']
    (HERE / '暦と観測量の点検.md').write_text('\n'.join(body) + '\n', encoding='utf-8')
    print(json.dumps(groups, ensure_ascii=False))


if __name__ == '__main__':
    main()
