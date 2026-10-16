"""固定済みE01_G_U台帳と保存価格から9月24日ナイトの損失経路を独立確認する。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
SESSION = '2026-09-24_Night'


def stamp(value: float) -> str:
    """
    機能: 保存価格の時刻を日本時間へ変換する。
    引数: value (float) はUnix秒。
    返り値: str のISO形式日時。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def main() -> None:
    """
    機能: 対象夜間の全組の会計・新規後順行限界・返済内訳を確認して保存する。
    引数: なし。
    返り値: None。戦略、元価格、台帳を変更しない。
    """
    with (ROOT / 'work/wave_v67/prepared/old23/new_inputs.pkl').open('rb') as stream:
        inputs = pickle.load(stream)
    with (ROOT / 'work/wave_v85/observed/ledgers/E01_G_U.pkl').open('rb') as stream:
        ledgers = pickle.load(stream)
    output = dict(対象=SESSION, 手法='E01_G_U', 約定='保存CurrentPriceで全経路再運転済みの台帳',
        会計='組は同一新規の全返済を合計する。脚は個別返済。手数料を各注文で切り捨て後に脚へ配賦する。',
        順行限界='新規からその組の全返済までの保存価格。将来を用いた事後診断であり売買条件ではない。',
        口座=[])
    for symbol in ('TOPIX', 'NK225'):
        ready, ledger = inputs[SESSION, symbol], ledgers[SESSION, symbol]
        price, times = ready['last'], ready['time_s']
        all_trades = ledger['net_trades']
        records = []
        for cycle in ledger['cycles']:
            cid, first, last, side = int(cycle[0]), int(cycle[1]), int(cycle[2]), int(cycle[8])
            trades = [t for t in all_trades if t['組'] == cid]
            entry = float(trades[0]['建値'])
            changes = side * (price[first:last + 1] - entry)
            best = first + int(np.argmax(changes))
            net = float(sum(t['収支'] for t in trades))
            assert abs(net - sum(float(t['利益損失前']) - float(t['手数料']) for t in trades)) < 1e-7
            records.append(dict(組=cid, 方向='買い' if side > 0 else '売り',
                新規=stamp(times[first]), 建値=entry, 全返済=stamp(times[last]),
                組収支=net, 固定ATR=float(cycle[5]),
                最大順行=float(changes.max()), 最大順行ATR=float(changes.max() / cycle[5]),
                最大順行時刻=stamp(times[best]), 最大順行価格=float(price[best]),
                最大逆行=float(changes.min()),
                返済=[dict(時刻=stamp(t['返済時刻']), 枚数=int(t['枚数']), 価格=float(t['返済値']),
                    理由=int(t['理由']), 収支=float(t['収支']), 手数料配賦=float(t['手数料'])) for t in trades]))
        # ----------------------------------------
        summary = dict(銘柄=symbol, 保存最初=float(price[0]), 保存最後=float(price[-1]),
            保存高値=float(price.max()), 保存安値=float(price.min()),
            組数=len(records), 黒字組=sum(r['組収支'] > 0 for r in records),
            組利益=sum(max(r['組収支'], 0.) for r in records),
            組損失=-sum(min(r['組収支'], 0.) for r in records),
            脚利益=float(sum(max(t['収支'], 0.) for t in all_trades)),
            脚損失=float(-sum(min(t['収支'], 0.) for t in all_trades)),
            手数料=float(sum(t['手数料'] for t in all_trades)),
            収支=sum(r['組収支'] for r in records), 各組=records)
        assert abs(summary['組利益'] - summary['組損失'] - summary['収支']) < 1e-7
        assert abs(summary['脚利益'] - summary['脚損失'] - summary['収支']) < 1e-7
        output['口座'].append(summary)
    # ----------------------------------------
    output['確認'] = [
        'TOPIXの利益0は全返済後の6組がすべて赤字だった意味で、部分利確や途中の含み益がなかった意味ではない。',
        'TOPIXでは6組のどれも新規後3ATRの順行に到達せず、幅0.75ATRへのトレール短縮条件は成立しなかった。',
        '方向が一時的に合っても、残玉の返済幅が広いため反転まで保有し、部分利確以上の残玉損失を生んだ。',
        '01:20の両銘柄買いは直前の急騰後に続くという想定が外れ、TOPIXは約4分、NK225は約5分で初期損切りになった。',
        '時刻回避中の損切りが主因ではない。NK225は22:15の予定全返済で10780円の利益。TOPIXはこの窓の強制決済なし。',
        'ルールの方向分岐は符号で対称。EMA条件はgap×方向>0.15、slow×方向>0.02を双方市場に共通使用し、売りだけを優遇する閾値はない。',
        '売買の対称な条件設定は上昇日と下落日の成績一致を意味しない。各場の値動きと方向別実績を別途確認する必要がある。',
    ]
    output['対称性の根拠'] = [
        'work/wave_v49/gates/gate_replay.py:181 gate_mask の方向との積による同一閾値',
        'work/wave_v67/engine_shadow.py:260 順行量を方向との積で評価、271行以降で同一追跡幅',
        'work/wave_v85/engine.py:195 発動・注文・数量は方向符号と共通設定に従う',
    ]
    target = HERE / '0924夜間独立確認.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
