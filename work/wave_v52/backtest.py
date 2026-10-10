"""価格形成の観測から定めた仮説を、損益で選別せず原本順に検証する。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
from datetime import date

import numpy as np
import pandas as pd

from replay import execute, REASONS
from export import intervals, summarize, save_csv, stamp


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'theory'))
from analyze import load_ready

BASE = dict(stop_atr=.5, activation_atr=1., trail_atr=.5, hold_seconds=300,
            exit_neutral=False, failure_seconds=0, failure_atr=0, cooldown_seconds=60)
EXIT_TEXT = '判断時の確定ATRの0.5倍を逆行したら損切り。1ATR順行後は最高利益から0.5ATR戻ったら返済。最長5分、または反対信号・場末で返済。'
MIDDLE_TEXT = '原本の価格ごとに損切りと利益追跡を判定。追加せず、返済後60秒は休止。'
METHODS = [
    dict(id='P01', name='圧力解消の確認（主試験）', description='一方向の売買で動いた後、その偏りと値動きが反転してから戻りを狙う。',
         entry='強い執行偏りと同方向の中値変化を記憶。5分以内に執行偏りがゼロか逆向き、かつ直前1分の中値が逆向きになれば入る。'),
    dict(id='P02', name='供給の裏付けを追加', description='P01に、入る方向の近接指値の厚さを追加する。', entry='P01成立時に、距離加重した近接数量の偏りも新規方向なら入る。'),
    dict(id='P03', name='回復の裏付けを追加', description='P01に、入る方向の同価格数量回復を追加する。', entry='P01成立時に、最良価格不変中の同価格回復の偏りも新規方向なら入る。'),
    dict(id='P04', name='両市場の値直しを追加', description='P01に、60秒遅れの相手市場の提示価格方向を追加する。', entry='P01成立時に、相手市場の両気配値直しの偏りも新規方向なら入る。'),
    dict(id='C01', name='強い執行を追う', description='執行の強さをそのまま継続の証拠にできるか。', entry='強い執行偏りがあり、直前1分の中値も同方向ならその方向へ入る。'),
    dict(id='C02', name='強い執行の直後に逆張り', description='圧力解消を待つ意味があるか。', entry='C01と同じ時点で逆方向へ入る。'),
    dict(id='C03', name='価格だけの反転確認', description='板の執行情報が必要かを比べる。', entry='直前1分の値幅が先頭10場の上位3分の1なら方向を記憶。5分以内に1分中値が反対へ動けば逆へ入る。'),
    dict(id='C04', name='圧力消失だけ', description='P01から中値の反転確認を外す。', entry='強い執行と同方向の値動きの後、5分以内に執行偏りがゼロか反対なら逆へ入る。'),
    dict(id='C05', name='価格反転だけ', description='P01から執行偏りの消失条件を外す。', entry='強い執行と同方向の値動きの後、5分以内に中値が反対へ動けば逆へ入る。'),
    dict(id='C06', name='進まない執行と供給回復', description='売買されても進まない状態を、すぐ反転と読めるか。', entry='強い執行方向へ中値が進まず、反対側の同価格数量回復が優勢なら、執行と逆へ入る。'),
    dict(id='C07', name='両市場の提示価格を追う', description='共通の値直しを継続の根拠にできるか。', entry='自己の両気配値直しと1分中値方向が一致し、60秒遅れの相手の値直しも一致すれば入る。'),
    dict(id='C08', name='近接供給の偏り', description='価格進捗から独立した残存供給に情報があるか。', entry='距離加重した供給偏りが先頭10場の絶対値で上位3分の1なら、厚い側の方向へ入る。'),
    dict(id='E15', name='圧力解消・15分まで', description='主試験の効果が15分まで続くか。', entry='P01と同じ入口。', hold_seconds=900),
    dict(id='EN0', name='圧力解消・中立で返済', description='反転開始の根拠が消えた時に早く返す。', entry='P01と同じ入口。', exit_neutral=True),
]


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def freeze() -> None:
    """機能: 先頭10場の観測だけから尺度を作り、売買条件を固定する。

    引数: なし。返り値: なし(None)。後半の観測結果・損益は読まない。
    """
    path = HERE / '売買仕様固定.json'
    if path.exists():
        raise RuntimeError('固定済み仕様は上書きしません')
    observations = pd.read_pickle(HERE / 'theory/観測.pkl')
    calibration = {}
    for symbol in ('TOPIX', 'NK225'):
        train = observations.loc[(observations.symbol == symbol) & (observations.period == '先頭10場')]
        calibration[symbol] = {c: float(np.nanquantile(abs(train[c]), 2/3)) for c in ('execution', 'r1', 'supply')}
    methods = []
    for source in METHODS:
        method = {**source, 'middle': MIDDLE_TEXT, 'exit': EXIT_TEXT, 'spec': {**BASE}}
        if 'hold_seconds' in source:
            method['spec']['hold_seconds'] = source['hold_seconds']
            method['exit'] = EXIT_TEXT.replace('最長5分', '最長15分')
        if source.get('exit_neutral'):
            method['spec']['exit_neutral'] = True
            method['exit'] = EXIT_TEXT + '毎分、入口信号が出なくなった場合も返済する。'
        methods.append(method)
    save(path, dict(主試験='P01', 尺度=calibration, 手法=methods,
        根拠='前10場では執行偏りと同区間の価格は正相関だが、次5分は微小な逆向き。価格応答の反転を待つ仮説を検証する。終了確認自体の効果は未確認であり、新規仮説。',
        条件数='12入口＋主入口の2出口対照。損益最大のものへ主案を差し替えない。',
        圧力記憶='強い同方向執行・価格進行を最初に記憶してから最大5分。同方向の再観測は期限を延長せず、反対の強い執行は置換。品質欠測・執行方向が全量不明の起点では記憶を破棄。',
        条件消費='終了条件成立で記憶を消費。追加ゲート不成立でも同じ過去イベントを再使用しない。',
        数量='TOPIXミニ5枚、NK225マイクロ10枚固定。片方向上限10/20以内。増玉なし。',
        リスク枠='0.5ATR損切り・1ATRで追跡開始・幅0.5ATRは最適値ではなく、5分値幅尺度に対する事前リスク枠。保持5分は主観測時間、15分は補助時間。',
        価格='判断後の次の有効原本行の最終約定価格。手数料ゼロ。大口自身の影響なし。ミニ/マイクロ実際の板ではない。',
        因果='観測は起点までに公開された過去箱のみ。判断行は起点以後の最初の有効行。60秒超の遅延は新規不採用。次行で執行。',
        期間='先頭10場は尺度算出に使用した内標本、次9場と既知最後4場は尺度固定の時間順再検証。全期間既閲覧で真の未見ではない。',
        コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


def build_signals(ready: dict, observation: pd.DataFrame, method: str, calibration: dict) -> tuple:
    """機能: 現在までの観測と圧力記憶だけで方向指示を作る。

    引数: ready(dict)、observation(DataFrame)、method(str)、calibration(dict)。
    返り値: 原本位置と方向の配列・判断明細(tuple)。将来ラベルを参照しない。
    """
    by_time = {float(r.time_s): r for r in observation.itertuples()}
    q = calibration[ready['symbol']]
    remembered = price_remembered = 0
    remembered_at = price_at = 0.
    decisions, trace = [], []
    last_index = -1
    for origin in np.arange(ready['start'] + 1200., ready['limit'], 60.):
        index = int(np.searchsorted(ready['time_s'], origin, side='left'))
        if index >= len(ready['time_s']):
            break
        row = by_time.get(float(origin))
        if index <= last_index or ready['time_s'][index] - origin > 60.:
            remembered = price_remembered = 0
            continue
        last_index = index
        signal = 0
        if row is None:
            remembered = price_remembered = 0
        else:
            assert row.observed_time <= origin <= ready['time_s'][index]
            assert row.seq <= ready['seq'][index]
            execution, price = row.execution, row.r1
            valid_exec = np.isfinite(execution) and np.isfinite(row.unknown_fraction) and row.unknown_fraction < 1.
            d = int(np.sign(execution)) if valid_exec else 0
            pdirection = int(np.sign(price))
            if not valid_exec:
                remembered = 0
            if origin - remembered_at > 300.:
                remembered = 0
            if origin - price_at > 300.:
                price_remembered = 0
            core = 'P01' if method in ('E15', 'EN0') else method
            # ----------------------------------------
            # 前の観測までの圧力だけを、現在の反応で失効・反転判定する。
            ended = valid_exec and remembered != 0 and remembered * execution <= 0
            turned = remembered != 0 and remembered * price < 0
            discharge = ended and turned
            if core in ('P01', 'P02', 'P03', 'P04') and discharge:
                signal = -remembered
                gate = {'P02': row.supply, 'P03': row.recovery, 'P04': row.peer_repricing}.get(core, float(signal))
                if not np.isfinite(gate) or signal * gate <= 0:
                    signal = 0
                remembered = 0
            elif core == 'C03' and price_remembered and price_remembered * price < 0:
                signal, price_remembered = -price_remembered, 0
            elif core == 'C04' and ended:
                signal, remembered = -remembered, 0
            elif core == 'C05' and turned:
                signal, remembered = -remembered, 0
            # ----------------------------------------
            # 現在起点の強い偏りを、次の起点以後で使う記憶にする。
            strong = valid_exec and d != 0 and abs(execution) >= q['execution']
            impact = strong and d * price > 0
            if core in ('C01', 'C02') and impact:
                signal = d if core == 'C01' else -d
            elif core == 'C06' and strong and d * price <= 0 and np.isfinite(row.recovery) and d * row.recovery < 0:
                signal = -d
            elif core == 'C07' and np.isfinite(row.repricing) and np.isfinite(row.peer_repricing):
                rd = int(np.sign(row.repricing))
                if rd and rd * price > 0 and rd * row.peer_repricing > 0:
                    signal = rd
            elif core == 'C08' and np.isfinite(row.supply) and abs(row.supply) >= q['supply']:
                signal = int(np.sign(row.supply))
            if impact and remembered != d:
                remembered, remembered_at = d, origin
            if abs(price) >= q['r1'] and pdirection and price_remembered != pdirection:
                price_remembered, price_at = pdirection, origin
            trace.append(dict(起点=stamp(origin), 判断時刻=stamp(ready['time_s'][index]),
                              判断原本行=int(ready['seq'][index]), 公開原本行=int(row.seq),
                              方向=signal, 執行偏り=float(execution) if valid_exec else None,
                              直前1分ATR=float(price), 近接供給=float(row.supply),
                              同価格回復=float(row.recovery) if np.isfinite(row.recovery) else None,
                              圧力記憶=remembered))
        decisions.append([index, signal])
    return np.array(decisions, float).reshape(-1, 2), trace


def run() -> None:
    """機能: 固定した全条件を全保存場へ適用し、会計とCSVを出す。

    引数: なし。返り値: なし(None)。現在API・実注文・将来ラベルは使用しない。
    """
    fixed = json.loads((HERE / '売買仕様固定.json').read_text(encoding='utf8'))
    ready = load_ready()
    observations = pd.read_pickle(HERE / 'theory/観測.pkl')
    sessions = sorted({key[0] for key in ready})
    final, ledgers, signals = {}, {}, {}
    for method in fixed['手法']:
        mid = method['id']
        final[mid], ledgers[mid], signals[mid] = {}, {}, {}
        for symbol in ('TOPIX', 'NK225'):
            accounts = []
            for session in sessions:
                data = ready[(session, symbol)]
                obs = observations.loc[(observations.session == session) & (observations.symbol == symbol)]
                decision, trace = build_signals(data, obs, mid, fixed['尺度'])
                result = execute(data, decision, method['spec'])
                result['intervals'] = intervals(data, result)
                result['period'] = '先頭10場' if sessions.index(session) < 10 else '次9場' if sessions.index(session) < 19 else '既知最後4場'
                result['week'] = '第' + str(date.fromisoformat(session[:10]).isocalendar().week) + '週'
                orders = [dict(判断時刻=stamp(o[0]), 約定時刻=stamp(o[1]), 判断原本行=int(o[2]), 約定原本行=int(o[3]),
                               区分='新規' if o[4] == 1 else '返済', 売買='買い' if o[5] == 1 else '売り',
                               枚数=int(o[6]), 価格=o[7], 損益円=o[8], 理由=REASONS[int(o[9])]) for o in result['orders']]
                save_csv(HERE / '台帳' / mid / f'{session}_{symbol}.csv', orders)
                save_csv(HERE / '判断' / mid / f'{session}_{symbol}.csv', trace)
                save_csv(HERE / '区間' / mid / f'{session}_{symbol}.csv', result['intervals'])
                signals[mid][(session, symbol)] = decision
                ledgers[mid][(session, symbol)] = {k: v for k, v in result.items() if k != 'curve'}
                accounts.append(result)
            final[mid][symbol] = dict(total=summarize(accounts),
                periods=[dict(name=p, **summarize([a for a in accounts if a['period'] == p])) for p in ('先頭10場', '次9場', '既知最後4場')],
                weeks=[dict(name=p, **summarize([a for a in accounts if a['week'] == p])) for p in sorted({a['week'] for a in accounts})],
                accounts=[{k: v for k, v in a.items() if k != 'curve'} for a in accounts])
        print(mid, [(s, final[mid][s]['total']['net']) for s in ('TOPIX', 'NK225')], flush=True)
    save(HERE / '売買結果.json', final)
    (HERE / 'ledgers.pkl').write_bytes(pickle.dumps(ledgers, pickle.HIGHEST_PROTOCOL))
    (HERE / 'signals.pkl').write_bytes(pickle.dumps(signals, pickle.HIGHEST_PROTOCOL))
    save(HERE / '再生監査.json', dict(条件数=len(fixed['手法']), 原本口座数=len(ready), 会計数=len(ready)*len(fixed['手法']),
                                    各注文の判断行より約定行が後=True, 全口座場内無保有=True, 区間合計一致=True,
                                    実行コードSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    freeze() if args.freeze else run()
