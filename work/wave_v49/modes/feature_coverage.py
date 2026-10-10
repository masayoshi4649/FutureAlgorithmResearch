"""原本更新頻度に左右されない模式の時間比と、初回利用可能時刻を整理する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

import numpy as np

import features as signals

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: エポック秒を日本時間へ変換する。

    引数: value(float)。返り値: 日本時間表記(str)。
    """
    return datetime.fromtimestamp(float(value), JST).strftime('%Y-%m-%d %H:%M:%S')


def first(times: np.ndarray, condition: np.ndarray) -> str | None:
    """機能: 条件が初めて成立した公開時刻を返す。

    引数: times/condition(ndarray)。返り値: 時刻又は未成立(str|None)。
    """
    rows = np.flatnonzero(condition)
    return stamp(times[rows[0]]) if len(rows) else None


def main() -> None:
    """機能: 全市場の模式を秒で集計し、説明と根拠JSONを保存する。

    引数: なし。返り値: なし(None)。損益は使用しない。
    """
    inputs, boards = signals.load_inputs()
    outputs = signals.build(inputs, boards)
    rows = []
    for key, ready in sorted(inputs.items()):
        item, times = outputs[key], ready['time_s']
        delta = np.diff(times)
        valid = (delta >= 0) & (delta <= 60)
        seconds = {str(mode): float(np.sum(delta[valid & (item['mode'][:-1] == mode)])) for mode in (0, 1, 2)}
        covered = float(np.sum(delta[valid]))
        missing = float(np.sum(delta[~valid]))
        assert abs(sum(seconds.values()) + missing - (times[-1] - times[0])) < 1e-6
        prices = {name: first(times, np.isfinite(item[name])) for name in ('support20', 'resistance20', 'center20')}
        rows.append(dict(session=key[0], symbol=key[1], 開始時刻=stamp(ready['start']),
            収録先頭時刻=stamp(times[0]), 収録末尾時刻=stamp(times[-1]),
            集計対象秒=covered, 長い空白除外秒=missing,
            最大原本時刻間隔秒=float(np.max(delta)), 模式別秒=seconds,
            模式別時間比={name: value / covered if covered else 0 for name, value in seconds.items()},
            初回追従時刻=first(times, item['mode'] == 1), 初回反復時刻=first(times, item['mode'] == 2),
            初回取引対象模式時刻=first(times, item['mode'] != 0),
            初回反復入口候補時刻=first(times, item['range_side'] != 0),
            初回板有効時刻=first(times, item['book_valid']), 初回吸収入口時刻=first(times, item['absorb_side'] != 0),
            支持抵抗初回時刻=prices))
    result = dict(全合格=True, 対象入力数=len(rows), 売買損益参照=False,
        集計定義='次行時刻との差を前行modeへ帰属。同秒差0。60秒超の空白は全秒を除外して別計上。収録先頭から末尾だけを集計し、場開始前後の未観測時間を足さない。',
        実装SHA256=hashlib.sha256((HERE / 'features.py').read_bytes()).hexdigest(),
        総模式秒={str(mode): sum(row['模式別秒'][str(mode)] for row in rows) for mode in (0, 1, 2)},
        総空白秒=sum(row['長い空白除外秒'] for row in rows), 明細=rows)
    signals.save(HERE / '模式の時間比.json', result)
    lines = [
        '# 自動で追従・反復・休みに分ける候補', '',
        'まだ利益を確認した完成手法ではなく、売買器へ渡す機械的な状況判定である。毎セッション初期化し、その場で既に公開された足と板だけを使う。', '',
        '- **追従**：両銘柄の移動平均の並びと傾きが現在も同じ向きで、直近20分の値動きに十分な一方向性がある。古い方向の保持はしない。',
        '- **反復**：両銘柄で往復が多く、自銘柄の変動幅が極端に拡大縮小せず、移動平均の乖離と過去範囲の幅も大きすぎない。範囲平均より十分安ければ買い候補、高ければ売り候補にする。',
        '- **休み**：どちらの条件にも合わない、公開情報が足りない、又は模式・方向が変わってから60秒経っていない。',
        '- **板の裏付け**：直近60秒の注文変化、近い板の30秒の変化、30秒の補充を合成。古い板や広い気配差は無効。吸収版では、売り推定が多いのに買い補充が優勢になり、近い板の動きも上向くことを買いの追加条件とする。売りは対称。',
        '- **支持・抵抗**：直近20実分の公開済み足の安値最小・高値最大を使用。後になって確定する転換点を過去の支持抵抗として使わない。', '',
        '## 開始直後の扱い', '',
        '反復はEMA60の計算と60秒の条件継続が必要で、最速でも開始からおよそ1時間2分後。'
        '追従はさらに3本分の傾きと相手の追加1分遅延を待つため、およそ1時間6分後となる。'
        '欠損足や条件不成立がある場合はさらに遅くなる。支持抵抗自体は足が公開された時から表示できるが、売買候補になるには模式の暖機を終える必要がある。'
        '序盤の波を取得できることはまだ確認しておらず、前場の情報を持ち越す仕様にもしていない。', '',
        '## 未検証の境界', '',
        'EMAの一方向性とERだけでは、急騰直後の天井と継続上昇を完全に区別できない。低ERもトレンド中の休憩を含み、反復の後の突破で負け得る。'
        '支持・抵抗は過去範囲であり、将来そこで必ず反転する価格ではない。', '',
        '板補充は「食われた分を同じ人が補充した」証明ではない。板減少には取消も含み、推定成行の買い売りも確定した注文主体の情報ではない。'
        'CurrentPriceTimeを公開時計の代理にしており、実際の受信時刻はない。源時刻から20秒を超える板を無効化するため、静かな時間では板方式だけ休みやすい。', '',
        '固定した閾値は損益を見て最適化していない。追従単独・反復単独・自動切替、板なし・板ありをそれぞれ売買再生して比較する必要がある。', '',
        '## 秒で数えた時間比と初回有効時刻', '',
        '原本行数の割合は更新頻度に偏るため使用しない。次行までの秒数を前行の模式へ積算し、60秒超の空白は除外して別計上した。'
        '各銘柄の収録先頭から末尾までが対象。終盤の返済期限後も特徴自体は記録する。', '',
        '|場|銘柄|追従|反復|休み|除外秒|初回有効|', '|---|---|---:|---:|---:|---:|---|'
    ]
    for row in rows:
        ratio = row['模式別時間比']
        lines.append(f'|{row["session"]}|{row["symbol"]}|{ratio["1"]:.1%}|{ratio["2"]:.1%}|{ratio["0"]:.1%}|'
                     f'{row["長い空白除外秒"]:.0f}|{row["初回取引対象模式時刻"] or "なし"}|')
    lines += ['', '数式と閾値は[特徴定義.json](特徴定義.json)、初回の追従・反復・板・支持抵抗時刻は[模式の時間比.json](模式の時間比.json)。'
                  '全32市場の先頭切断・未来改変・上下反射・同秒行切断は[特徴監査.json](特徴監査.json)です。', '']
    (HERE / '説明.md').write_text('\n'.join(lines), encoding='utf8')
    print(result['総模式秒'], '除外秒', result['総空白秒'])
    for row in rows[-2:]:
        print(row)


if __name__ == '__main__':
    main()
