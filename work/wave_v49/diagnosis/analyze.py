"""追加ナイトの共通入口と赤字の発生経路を保存台帳から説明する。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / 'work/wave_v48/update_20261001'
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
sys.path.insert(0, str(ROOT / 'work/wave_v47'))
import component_signals as signals

IDS = ('F50_NONE__E11', 'F50_NONE__E10', 'C01__E10', 'A0__E10')
REASONS = {1: '組の損失上限', 2: 'トレーリング返済', 7: '一部利確',
           8: '保有時間上限', 9: '場内返済', 30: '悪化で減量', 31: '数量復元', 32: '実組の損失予算'}
JST = timezone(timedelta(hours=9))


def read(path: Path) -> object:
    """機能: 保存済みの圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    return json.loads(gzip.decompress(path.read_bytes()))


def stamp(seconds: float) -> str:
    """機能: エポック秒を日本時間へ変換する。

    引数: seconds(float)。返り値: 日本時間(str)。
    """
    return datetime.fromtimestamp(float(seconds), JST).strftime('%Y-%m-%d %H:%M:%S')


def scalar(value: object) -> float | None:
    """機能: 数値を有限のJSON値へ統一する。

    引数: value(object)。返り値: 数値又は欠損(float|None)。
    """
    return float(value) if np.isfinite(value) else None


def model(ready: dict, params: dict) -> dict:
    """機能: 公開確定足だけで主方向の構成数値を再現する。

    引数: ready/params(dict)。返り値: 公開時刻、EMA、傾き、価格変化(dict)。
    """
    hierarchy = signals.HIERARCHY
    bars = hierarchy.LEGACY._bars(ready)
    close = pd.Series(np.asarray(bars['close'], float))
    atr = np.asarray(bars['atr'], float)
    fast = close.ewm(span=15, adjust=False, min_periods=15).mean()
    slow = close.ewm(span=60, adjust=False, min_periods=60).mean()
    gap = (fast - slow).to_numpy(float) / atr
    slope = slow.diff(3).to_numpy(float) / atr
    result = dict(time_s=np.asarray(bars['time_s'], float), close=close.to_numpy(float), atr=atr,
                  gap=gap, slope=slope, slow=slow.to_numpy(float), fast=fast.to_numpy(float),
                  direction=hierarchy._main_from_bars(bars, params))
    for minutes in (5, 15, 30):
        earlier = hierarchy._asof(result['time_s'], result['close'], result['time_s'] - minutes * 60, np.nan)
        result[f'change_{minutes}m'] = result['close'] - earlier
        result[f'change_{minutes}m_atr'] = result[f'change_{minutes}m'] / atr
    return result


def snapshot(m: dict, seconds: float, delay: float) -> dict:
    """機能: 指定時点までに公開された確定足のみを調べる。

    引数: m(dict)、seconds/delay(float)。返り値: 当時利用可能な方向と変化(dict)。
    """
    index = int(np.searchsorted(m['time_s'] + delay, seconds, side='right') - 1)
    assert index >= 0
    result = dict(参照足開始=stamp(m['time_s'][index] - 120),
                  通常公開時刻=stamp(m['time_s'][index]), 利用時刻=stamp(m['time_s'][index] + delay),
                  参照遅延秒=delay, 主方向=int(m['direction'][index]),
                  終値=scalar(m['close'][index]), ATR=scalar(m['atr'][index]),
                  EMA間隔ATR比=scalar(m['gap'][index]), 長期EMA直近3本傾きATR比=scalar(m['slope'][index]),
                  現在新規主方向条件=int(1 if m['gap'][index] > .15 and m['slope'][index] > .02
                                       else -1 if m['gap'][index] < -.15 and m['slope'][index] < -.02 else 0))
    for minutes in (5, 15, 30):
        result[f'直近{minutes}分変化'] = scalar(m[f'change_{minutes}m'][index])
        result[f'直近{minutes}分変化ATR比'] = scalar(m[f'change_{minutes}m_atr'][index])
    return result


def event_snapshot(ready: dict, models: dict, state: np.ndarray, row: int) -> dict:
    """機能: 一つの原本行で自市場と相手市場を照合する。

    引数: ready/models(dict)、state(ndarray)、row(int)。返り値: 入口当時の比較(dict)。
    """
    symbol = ready['symbol']
    peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    time_s = float(ready['time_s'][row])
    own = snapshot(models[symbol], time_s, 0.)
    other = snapshot(models[peer], time_s, 60.)
    latest_peer = snapshot(models[peer], time_s, 0.)
    short = models[symbol]['short']
    index = int(np.searchsorted(short['seq'], ready['seq'][row], side='right') - 1)
    supporting = np.flatnonzero((np.arange(len(short['seq'])) <= index)
                               & (short['main'] == state[row])
                               & (short['short'] * state[row] > .05))
    support = int(supporting[-1]) if len(supporting) else -1
    return dict(原本行=row, 原本seq=int(ready['seq'][row]), 時刻=stamp(time_s),
                観測価格=scalar(ready['last'][row]), 共通入口方向=int(state[row]),
                最新短期30秒変化ATR比=scalar(short['short'][index]),
                最新短期30秒公開時刻=stamp(short['time_s'][index]),
                最終短期支持時刻=stamp(short['time_s'][support]) if support >= 0 else None,
                最終短期支持からの秒数=time_s - short['time_s'][support] if support >= 0 else None,
                自銘柄=own, 相手銘柄=other, 相手追加遅延なし参考=latest_peer,
                主方向不一致=own['主方向'] != other['主方向'],
                現在傾き正負不一致=own['長期EMA直近3本傾きATR比'] * other['長期EMA直近3本傾きATR比'] < 0,
                変化方向不一致={str(minutes): own[f'直近{minutes}分変化'] * other[f'直近{minutes}分変化'] < 0
                              for minutes in (5, 15, 30)})


def main() -> None:
    """機能: 初回組ごとの原因資料と方式間差を生成する。

    引数: なし。返り値: なし(None)。新作業領域だけへ保存する。
    """
    inputs = pickle.loads((SOURCE / 'new_inputs.pkl').read_bytes())
    features = pickle.loads((SOURCE / 'new_features_depth.pkl').read_bytes())
    spec = signals.specification()
    signals.set_root(ROOT)
    params = signals.legacy_spec(spec)['params']
    assert params['main_kind'] == 'ema15_60' and params['time_multiplier'] == 1 and params['clock_multiplier'] == 1
    state = signals.build(spec, inputs, features)
    models = {key[1]: model(ready, params) for key, ready in inputs.items()}
    main_models = {key: dict(time_s=models[key[1]]['time_s'], direction=models[key[1]]['direction']) for key in inputs}
    for key, ready in inputs.items():
        short = signals.short_model(ready, features[key], 1.)
        models[key[1]]['short'] = dict(short, main=signals.HIERARCHY._allowed(key, short['time_s'], main_models, params))
    ledgers = {identifier: {r['symbol']: r for r in read(SOURCE / f'ledgers/{identifier}.json.gz')} for identifier in IDS}
    sessions = {identifier: {r['symbol']: r for r in read(SOURCE / f'sessions/{identifier}.json.gz')} for identifier in IDS}
    campaigns = []
    for key, ready in inputs.items():
        symbol = key[1]
        mult = 1000 if symbol == 'TOPIX' else 10
        base = ledgers[IDS[0]][symbol]
        all_orders = {identifier: np.array(ledgers[identifier][symbol]['orders']) for identifier in IDS}
        for identifier in IDS[1:]:
            np.testing.assert_array_equal(base['entry_preparations'], ledgers[identifier][symbol]['entry_preparations'])
            left, right = all_orders[IDS[0]], all_orders[identifier]
            np.testing.assert_array_equal(left[(left[:, 6] == 20) & (left[:, 7] == 1)],
                                          right[(right[:, 6] == 20) & (right[:, 7] == 1)])
        for cycle in base['cycles']:
            cid, start, end = map(int, cycle[:3])
            direction, atr = int(cycle[8]), float(cycle[5])
            orders = all_orders[IDS[0]]
            opening = orders[(orders[:, 2] == cid) & (orders[:, 6] == 20)][0]
            entry_price = float(opening[5])
            entry_prep = next(r for r in base['entry_preparations'] if int(r[0]) == cid)
            rows = dict(準備=int(entry_prep[3]), 注文水準最終更新=int(opening[1]), 約定直前=start - 1, 約定=start)
            events = {name: event_snapshot(ready, models, state[key], row) for name, row in rows.items()}
            path = direction * (ready['last'][start:end + 1] - entry_price)
            mfe, mae = max(0., float(np.max(path))), max(0., float(-np.min(path)))
            method_results = {}
            for identifier in IDS:
                cs = next(r for r in ledgers[identifier][symbol]['cycles'] if int(r[0]) == cid)
                oo = all_orders[identifier]
                trades = oo[(oo[:, 2] == cid) & (oo[:, 7] == 0)]
                method_results[identifier] = dict(収支円=cs[3] * mult,
                    決済時刻=stamp(ready['time_s'][int(cs[2])]), 最終返済理由=REASONS.get(int(cs[9]), str(cs[9])),
                    返済脚=[dict(時刻=stamp(ready['time_s'][int(r[0])]), 枚数=int(r[4]), 価格=float(r[5]),
                               理由=REASONS.get(int(r[6]), str(r[6]))) for r in trades])
            info = dict(銘柄=symbol, 組=cid, 方向='買い' if direction == 1 else '売り',
                        初回価格=entry_price, 初回ATR=atr, 初回枚数=int(opening[4]),
                        エントリー時刻=stamp(ready['time_s'][start]), 決済時刻=stamp(ready['time_s'][end]),
                        保有分=(ready['time_s'][end] - ready['time_s'][start]) / 60,
                        順行最大幅=mfe, 逆行最大幅=mae, 順行最大ATR比=mfe / atr, 逆行最大ATR比=mae / atr,
                        エントリー状況=events, 各方式結果=method_results,
                        現在買売条件不成立_準備=any(events['準備'][side]['現在新規主方向条件'] != direction for side in ('自銘柄', '相手銘柄')),
                        現在買売条件不成立_直前=any(events['約定直前'][side]['現在新規主方向条件'] != direction for side in ('自銘柄', '相手銘柄')),
                        傾き逆行_直前=[side for side in ('自銘柄', '相手銘柄')
                                      if direction * events['約定直前'][side]['長期EMA直近3本傾きATR比'] < 0],
                        変化逆行_直前={str(minutes): [side for side in ('自銘柄', '相手銘柄')
                                                     if direction * events['約定直前'][side][f'直近{minutes}分変化'] < 0]
                                            for minutes in (5, 15, 30)})
            campaigns.append(info)
    summary = {}
    for symbol in ('TOPIX', 'NK225'):
        chosen = [r for r in campaigns if r['銘柄'] == symbol]
        for identifier in IDS:
            assert abs(sum(r['各方式結果'][identifier]['収支円'] for r in chosen) - sessions[identifier][symbol]['net_yen']) < 1e-6
        summary[symbol] = dict(組数=len(chosen),
            方式別収支={identifier: sessions[identifier][symbol]['net_yen'] for identifier in IDS},
            買売別={side: dict(組数=sum(r['方向'] == side for r in chosen),
                収支円=sum(r['各方式結果'][IDS[0]]['収支円'] for r in chosen if r['方向'] == side)) for side in ('買い', '売り')},
            入口主方向不一致数={stage: sum(r['エントリー状況'][stage]['主方向不一致'] for r in chosen)
                              for stage in ('準備', '注文水準最終更新', '約定直前', '約定')},
            当時の価格変化不一致組={str(minutes): [r['組'] for r in chosen
                                                   if r['エントリー状況']['約定直前']['変化方向不一致'][str(minutes)]] for minutes in (5, 15, 30)},
            主方向開始条件未成立組=[r['組'] for r in chosen if r['現在買売条件不成立_直前']],
            傾き逆行組=[r['組'] for r in chosen if r['傾き逆行_直前']],
            損失組の1_5ATR未到達数=sum(r['各方式結果'][IDS[0]]['収支円'] < 0 and r['順行最大ATR比'] < 1.5 for r in chosen),
            順行3ATR到達組=[r['組'] for r in chosen if r['順行最大ATR比'] >= 3.])
    paths = [SOURCE / 'new_inputs.pkl', SOURCE / 'new_features_depth.pkl', Path(__file__)]
    paths += [SOURCE / f'{folder}/{identifier}.json.gz' for identifier in IDS for folder in ('sessions', 'ledgers')]
    output = dict(対象='2026-09-30_Night', API取得数=0, 条件変更=False, 全合格=True, 概要=summary,
                  調査対象組=campaigns,
                  注意='MFE/MAEは事後の原因分析だけに使用。入口の状況は当時公開済み確定足のみ。5/15/30分変化は足本数でなく実時間差のasof。注文水準最終更新はトレーリング更新元であり約定可否の再判定行ではない。',
                  参照SHA256={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE / '原因の証拠.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    explanation(output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in campaigns:
        e = r['エントリー状況']['約定直前']
        print(r['銘柄'], r['組'], r['エントリー時刻'], r['方向'], r['各方式結果'][IDS[0]]['収支円'],
              'MFE', round(r['順行最大ATR比'], 2), 'gap/slope',
              [(round(e[s]['EMA間隔ATR比'], 2), round(e[s]['長期EMA直近3本傾きATR比'], 2)) for s in ('自銘柄','相手銘柄')],
              '5/15/30', [(e[s]['直近5分変化'],e[s]['直近15分変化'],e[s]['直近30分変化']) for s in ('自銘柄','相手銘柄')])


def explanation(output: dict) -> None:
    """機能: 検証事実と未確定の改善案を短い説明へ分ける。

    引数: output(dict)。返り値: なし(None)。原因の証拠から表を作る。
    """
    lines = [
        '# 9月30日ナイトの赤字原因', '',
        '全18初回は、TOPIXとNKの保持している主方向が一致した時に入っていた。'
        '主因は方向の不一致を無視したことではなく、21時35分以降の往復を継続する波と判定し、損切り後も再び入ったこと。', '',
        '候補1ではTOPIXが中間6連敗で−130,500円、前後の売り2組で＋96,500円、計−34,000円。'
        'NKが中間8連敗で−95,000円、前後の売り2組で＋27,000円、計−68,000円。'
        'TOPIXの買い5組は全敗−105,500円、売り3組は＋71,500円。NKの買い5組も全敗−58,000円、売り5組は−10,000円。', '',
        '## 入口で何が起きていたか', '',
        '- 保持主方向はEMA15/60の間隔と長期線の傾きで開始し、EMA間隔が逆符号になるまで残る。傾きの弱まりや反転だけでは取り消さない。',
        '- 自市場は1分足の開始から120秒後に公開した足、相手はさらに60秒遅らせた足を参照する。同一の現在秒の価格が同方向という保証ではない。',
        '- 短期30秒変化による支持も、最後の支持から最大120秒残る。最新の30秒変化が逆向きでも入口状態が残り得る。',
        '- 新規注文は前行までに設置されたトレーリング水準で約定する。注文水準最終更新行と準備行、約定直前行、約定行は別に記録した。今回18件は全段階で両市場の保持主方向が一致していた。', '',
        '具体例はNKの22:24買い。両市場とも直近5・15・30分価格が下落し、最新の長期EMA傾きも下向きなのに、上向きの保持状態が残っていた。'
        'NKの23:01売りでは、NKの最新EMA傾きは上向き、TOPIXは下向き。両市場の5・15分価格は上昇していた。この2組は各−12,000円。'
        'この意味では「根拠が弱まったら見送る」という問題提起は当たっている。', '',
        '一方、21:35の買いは両市場の主方向・傾き・5/15/30分変化がすべて上向きでも失敗した。'
        '同方向一致だけでは、その後も伸びる保証にならない。', '',
        '## 途中・出口で何が起きていたか', '',
        '候補1のNKの負け8組すべてと、TOPIXの負け6組中5組は、含み益が1.5ATRまで一度も伸びなかった。'
        'そのため1.5ATR後の数量減量や3ATR後のトレーリング短縮が損失の大半に介入できず、ほぼ1ATRの損切りを積み重ねた。'
        'TOPIXの23:36買いだけは1.61ATR伸び、2枚を減らしたため−5,500円。途中減量なしの候補4は同じ組で−27,500円だった。', '',
        '## 4候補の差', '',
        '入口の準備・初回時刻・価格・枚数は4候補で完全一致。差は途中と出口だけ。', '',
        '|銘柄|候補1|候補2|候補3|候補4|',
        '|---|---:|---:|---:|---:|'
    ]
    for symbol in ('TOPIX', 'NK225'):
        values = output['概要'][symbol]['方式別収支']
        lines.append('|' + symbol + '|' + '|'.join(f'{values[x]:+,.0f}円' for x in IDS) + '|')
    lines += ['',
        '候補2が候補1を上回った差（TOPIX＋25,500円、NK＋4,000円）は、最後の売り1組でトレーリング幅を広く保ち、さらに下落する部分を取れた差。'
        'それ以前の損失組は候補1・2で同じだった。候補3・4との違いは減量と復元。NKでは持ち続ける候補4の勝ち2組が＋38,500円となり、候補1の＋27,000円より大きかった。', '',
        '## 見送り案について確定したこと', '',
        '単純に「両市場の5分騰落が反対なら除外」すると、当夜の勝ち売りである両市場18:08とTOPIX00:28が該当する。'
        '「主方向を保持中でも現在の傾きが逆なら新規停止」はNK22:24・23:01の問題を直接扱うが、実際の改良損益は新規時刻がずれるため全注文を再生しないと分からない。'
        'この診断は元の取引を事後削除した収支を改善成績としていない。', '',
        '## 全初回組の証拠', '',
        '以下の最大順行は候補1の保有中に観測された値。原因分析にだけ使用し、入口判定には使っていない。'
        '各方式の返済脚、準備時・注文更新時・約定直前・約定時の公開済み足の数値は[原因の証拠.json](原因の証拠.json)を参照。', '',
        '|銘柄|組|初回|方向|候補1収支|最大順行ATR|直前の事実|',
        '|---|---:|---|---|---:|---:|---|'
    ]
    for row in output['調査対象組']:
        e = row['エントリー状況']['約定直前']
        facts = []
        if row['傾き逆行_直前']:
            facts.append('EMA傾き逆行:' + '・'.join(row['傾き逆行_直前']))
        elif row['現在買売条件不成立_直前']:
            facts.append('主方向の開始閾値未達だが保持中')
        if row['変化逆行_直前']['15']:
            facts.append('15分変化逆行:' + '・'.join(row['変化逆行_直前']['15']))
        direction = 1 if row['方向'] == '買い' else -1
        if direction * e['最新短期30秒変化ATR比'] < 0:
            facts.append(f'最新30秒逆行、支持{e["最終短期支持からの秒数"]:.0f}秒前')
        if not facts:
            facts.append('保持主方向・最新傾きとも一致')
        lines.append(f'|{row["銘柄"]}|{row["組"]}|{row["エントリー時刻"][11:]}|{row["方向"]}|'
                     f'{row["各方式結果"][IDS[0]]["収支円"]:+,.0f}円|{row["順行最大ATR比"]:.2f}|{" / ".join(facts)}|')
    lines += ['', '初回TOPIXミニ5枚・NKマイクロ10枚、片方向上限10枚・20枚。費用ゼロ・指定価格約定の既存条件を維持。'
                  '保存済みデータだけを読み取り、API取得・注文送信・旧成果の変更は行っていない。', '']
    (HERE / '赤字原因.md').write_text('\n'.join(lines), encoding='utf8')


if __name__ == '__main__':
    main()
