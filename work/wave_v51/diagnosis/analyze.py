"""E01の全23場を独立会計し、直近損失の入口・保有・出口を分解する。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
_spec = importlib.util.spec_from_file_location('既存入口診断', ROOT / 'work/wave_v49/diagnosis/analyze.py')
old = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = old
_spec.loader.exec_module(old)
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'numba_cache')
signals = old.signals
JST = timezone(timedelta(hours=9))
RECENT = ('2026-10-02_Night', '2026-10-05_Day', '2026-10-05_Night', '2026-10-06_Day')
REASONS = {1: '初期損切り', 2: '追跡返済', 7: '部分利確', 8: '保有360分', 9: '場内返済', 11: '早期保護', 30: '悪化で半減', 31: '復元', 32: '実組損失上限'}


def read(path: Path) -> object:
    """機能: 保存JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def stamp(value: float) -> str:
    """機能: 観測秒を日本時間へ変換する。

    引数: value(float)。返り値: 日本時間(str)。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat(timespec='seconds')


def group(rows: list[dict]) -> dict:
    """機能: 組単位の勝敗と入口特徴を集計する。

    引数: rows(list[dict])。返り値: 集計(dict)。
    """
    wins = [r for r in rows if r['収支円'] > 0]
    losses = [r for r in rows if r['収支円'] < 0]
    result = dict(組数=len(rows), 勝ち組数=len(wins), 負け組数=len(losses),
                  利益円=sum(r['収支円'] for r in wins), 損失円=-sum(r['収支円'] for r in losses),
                  収支円=sum(r['収支円'] for r in rows),
                  負け組MFE1_5ATR未達=sum(r['MFE_ATR'] < 1.5 for r in losses),
                  負け組MFE0_5ATR未達=sum(r['MFE_ATR'] < .5 for r in losses))
    for label, subset in (('勝ち', wins), ('負け', losses)):
        result[label] = dict(保有分中央値=float(np.median([r['保有分'] for r in subset])) if subset else None,
            MFE_ATR中央値=float(np.median([r['MFE_ATR'] for r in subset])) if subset else None,
            EMA開始条件失効数=sum(r['開始条件失効'] for r in subset),
            長期傾き逆行数=sum(r['長期傾き逆行'] for r in subset),
            変化不一致数={str(w): sum(r['変化不一致'][str(w)] for r in subset) for w in (5, 15, 30)},
            変化逆行数={str(w): sum(r['変化逆行'][str(w)] for r in subset) for w in (5, 15, 30)})
    return result


def main() -> None:
    """機能: 全場の入力・保存台帳を照合して原因資料を保存する。

    引数: なし。返り値: なし(None)。書込先は今回診断領域のみ。
    """
    inputs = pickle.loads((ROOT / 'work/wave_v47/inputs.pkl').read_bytes())
    features = pickle.loads((ROOT / 'work/wave_v47/features_depth.pkl').read_bytes())
    sources = [ROOT / 'work/wave_v49/early']
    for name in ('update_20260930', 'update_20261001'):
        folder = ROOT / 'work/wave_v48' / name
        inputs.update(pickle.loads((folder / 'new_inputs.pkl').read_bytes()))
        features.update(pickle.loads((folder / 'new_features_depth.pkl').read_bytes()))
    for name in read(ROOT / 'work/wave_v50/追加結果一覧.json'):
        folder = ROOT / 'work/wave_v50' / name
        sources.append(folder)
        inputs.update(pickle.loads((folder / 'new_inputs.pkl').read_bytes()))
        features.update(pickle.loads((folder / 'new_features_depth.pkl').read_bytes()))
    ledgers = [r for source in sources for r in read(source / 'ledgers/E01.json.gz')]
    sessions = {(r['session'], r['symbol']): r for source in sources for r in read(source / 'sessions/E01.json.gz')}
    assert len(inputs) == len(ledgers) == len(sessions) == 46
    spec = signals.specification()
    signals.set_root(ROOT)
    params = signals.legacy_spec(spec)['params']
    states = signals.build(spec, inputs, features)
    models = {key: old.model(ready, params) for key, ready in inputs.items()}
    main_models = {key: dict(time_s=m['time_s'], direction=m['direction']) for key, m in models.items()}
    for key, ready in inputs.items():
        short = signals.short_model(ready, features[key], 1.)
        models[key]['short'] = dict(short, main=signals.HIERARCHY._allowed(key, short['time_s'], main_models, params))
    campaigns, paths, payments, proof = [], [], [], []
    for ledger in ledgers:
        key = ledger['session'], ledger['symbol']
        ready = inputs[key]
        multiplier = 1000 if key[1] == 'TOPIX' else 10
        orders = np.asarray(ledger['orders'], float).reshape((-1, 8))
        trades = np.asarray(ledger['trades'], float).reshape((-1, 11))
        pnl = trades[:, 2] * trades[:, 3] * (trades[:, 5] - trades[:, 4]) * multiplier
        np.testing.assert_allclose(pnl, trades[:, 10] * multiplier, atol=1e-7, rtol=0)
        assert abs(pnl.sum() - sessions[key]['net_yen']) < 1e-6
        for t, amount in zip(trades, pnl):
            payments.append(dict(セッション=key[0], 銘柄=key[1], 組=int(t[0]), 返済理由=REASONS.get(int(t[9]), str(int(t[9]))),
                枚数=int(t[3]), 収支円=float(amount), 時刻=stamp(ready['time_s'][int(t[7])])))
        scheduler = {int(r[0]): r for r in ledger['scheduler_cycles']}
        for cycle in ledger['cycles']:
            cid, start, end = map(int, cycle[:3])
            direction, atr = int(cycle[8]), float(cycle[5])
            opening = orders[(orders[:, 2] == cid) & (orders[:, 7] == 1)][0]
            entry = float(opening[5])
            path = direction * (ready['last'][start:end + 1] - entry)
            prep = next(r for r in ledger['entry_preparations'] if int(r[0]) == cid)
            local_models = {symbol: models[(key[0], symbol)] for symbol in ('TOPIX', 'NK225')}
            snapshots = {label: old.event_snapshot(ready, local_models, states[key], row)
                         for label, row in (('準備', int(prep[3])), ('直前', start - 1))}
            snap = snapshots['直前']
            slow_staleness = {}
            contrary_signal = {}
            for symbol in ('TOPIX', 'NK225'):
                model = models[(key[0], symbol)]
                delay = 0 if symbol == key[1] else 60
                published = model['time_s'] + delay
                at = int(np.searchsorted(published, ready['time_s'][start-1], side='right')-1)
                before = at
                while before >= 0 and model['slope'][before]*direction < 0:
                    before -= 1
                slow_staleness[symbol] = float((ready['time_s'][start-1]-published[before+1])/60) if before < at else 0.
                changed = np.flatnonzero((published >= ready['time_s'][start]) & (published <= ready['time_s'][end])
                    & (model['direction'] == -direction))
                contrary_signal[symbol] = dict(保有中に保持主方向反転=bool(len(changed)))
                if len(changed):
                    t = published[changed[0]]
                    contrary_signal[symbol].update(最初の反転公開時刻=stamp(t), 反転から返済まで分=float((ready['time_s'][end]-t)/60))
            end_shadow = int(scheduler[cid][2])
            after_exit = ready['last'][end:end_shadow + 1]
            shadow_moves = dict(待機分=(ready['time_s'][end_shadow] - ready['time_s'][end]) / 60,
                待機終了時刻=stamp(ready['time_s'][end_shadow]),
                返済観測価格=float(after_exit[0]), 待機終了価格=float(after_exit[-1]),
                旧方向最大値幅=float(np.max(direction * (after_exit-after_exit[0]))),
                反対方向最大値幅=float(np.max(-direction * (after_exit-after_exit[0]))))
            opposite = np.flatnonzero(states[key][end + 1:end_shadow + 1] == -direction)
            shadow_moves['待機中に反対入口信号'] = bool(len(opposite))
            if len(opposite):
                shadow_moves['反対入口信号時刻'] = stamp(ready['time_s'][end + 1 + opposite[0]])
            wait_rows = np.arange(end + 1, end_shadow + 1)
            same = wait_rows[(states[key][wait_rows] == direction)
                & (ready['time_s'][wait_rows] >= ready['time_s'][end] + 300)]
            shadow_moves['5分待機後に同方向入口信号'] = bool(len(same))
            if len(same):
                shadow_moves['5分待機後の同方向入口信号時刻'] = stamp(ready['time_s'][same[0]])
                shadow_moves['5分待機後の同方向入口信号価格'] = float(ready['last'][same[0]])
            row = dict(セッション=key[0], 銘柄=key[1], 組=cid, 方向='買い' if direction > 0 else '売り',
                初回枚数=int(opening[4]), 初回価格=entry, 初回ATR=atr, 入口時刻=stamp(ready['time_s'][start]),
                返済時刻=stamp(ready['time_s'][end]), 保有分=float((ready['time_s'][end]-ready['time_s'][start])/60),
                収支円=float(cycle[3]*multiplier), MFE_ATR=max(0., float(path.max()/atr)),
                MAE_ATR=max(0., float(-path.min()/atr)),
                初回全枚数での最大含み益円=max(0., float(path.max()*int(opening[4])*multiplier)),
                返済理由=REASONS.get(int(cycle[9]), str(int(cycle[9]))), 入口状況=snapshots,
                入口時点の長期EMA逆傾き継続分=slow_staleness, 保有中の主方向反転=contrary_signal,
                開始条件失効=any(snap[s]['現在新規主方向条件'] != direction for s in ('自銘柄', '相手銘柄')),
                長期傾き逆行=any(snap[s]['長期EMA直近3本傾きATR比']*direction < 0 for s in ('自銘柄', '相手銘柄')),
                変化不一致=snap['変化方向不一致'],
                変化逆行={str(w): any(snap[s][f'直近{w}分変化']*direction < 0 for s in ('自銘柄', '相手銘柄')) for w in (5, 15, 30)},
                通常影待機=shadow_moves)
            campaigns.append(row)
        chosen = [r for r in campaigns if (r['セッション'], r['銘柄']) == key]
        assert abs(sum(r['収支円'] for r in chosen)-float(pnl.sum())) < 1e-6
        m = models[key]
        close, times = m['close'], m['time_s']
        price = ready['last']
        high_i, low_i = int(np.argmax(price)), int(np.argmin(price))
        valid = np.isfinite(m['atr']) & (m['atr'] > 0)
        nonzero = m['direction'][m['direction'] != 0]
        summaries = group(chosen)
        paths.append(dict(セッション=key[0], 銘柄=key[1], 始値=float(price[0]), 終値=float(price[-1]),
            始終変化=float(price[-1]-price[0]), 高値=float(price.max()), 安値=float(price.min()),
            高値時刻=stamp(ready['time_s'][high_i]), 安値時刻=stamp(ready['time_s'][low_i]),
            値幅=float(price.max()-price.min()), ATR中央値=float(np.median(m['atr'][valid])),
            始終差対値幅=float(abs(price[-1]-price[0])/(price.max()-price.min())),
            確定足方向効率=float(abs(close[-1]-close[0])/np.abs(np.diff(close)).sum()),
            保持方向転換数=int(np.sum(nonzero[1:]*nonzero[:-1] == -1)),
            **summaries))
        proof.append(dict(セッション=key[0], 銘柄=key[1], 台帳収支円=float(pnl.sum()),
            既存報告収支円=float(sessions[key]['net_yen']), 会計一致=True))
    # ----------------------------------------
    # 入口特徴は当時公開済み情報だけ、順行幅と待機中値幅は原因説明専用の事後値。
    groups = {}
    for symbol in ('TOPIX', 'NK225'):
        for label, names in (('旧19', {r['session'] for r in ledgers} - set(RECENT)), ('追加4', set(RECENT)), ('全23', {r['session'] for r in ledgers})):
            chosen = [r for r in campaigns if r['銘柄'] == symbol and r['セッション'] in names]
            groups[symbol + '_' + label] = group(chosen)
    reasons = []
    for symbol in ('TOPIX', 'NK225'):
        for label, names in (('旧19', {r['session'] for r in ledgers} - set(RECENT)), ('追加4', set(RECENT))):
            rows = [r for r in payments if r['銘柄'] == symbol and r['セッション'] in names]
            for reason in sorted({r['返済理由'] for r in rows}):
                subset = [r for r in rows if r['返済理由'] == reason]
                reasons.append(dict(銘柄=symbol, 期間=label, 理由=reason, 返済脚数=len(subset),
                    利益円=sum(max(0, r['収支円']) for r in subset), 損失円=-sum(min(0, r['収支円']) for r in subset),
                    収支円=sum(r['収支円'] for r in subset)))
    result = dict(全合格=True, API取得数=0, 会計照合=proof, 集計=groups, 原因別= reasons,
        セッション経路=paths, 全取引=campaigns, 全返済=payments,
        注意='MFE/MAEと通常影待機中の値幅は事後分析。待機を外した場合の実現可能な利益を示さない。初回全枚数の最大含み益は減量後も全枚数を仮定する価格経路指標。特徴の有無による比較は因果効果ではない。')
    (HERE / '原因の証拠.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    report(result)
    print(json.dumps(dict(集計=groups, 原因別=reasons), ensure_ascii=False, indent=2))


def report(result: dict) -> None:
    """機能: 日別損益と各組の原因を簡潔な日本語表へまとめる。

    引数: result(dict)。返り値: なし(None)。
    """
    lines = ['# E01連続赤字の分解', '', '全23場・両銘柄46口座で、返済価格×枚数×倍率から再計算した収支が既存報告と一致。原本/APIは変更・取得していない。', '',
        '## 確認できた原因', '',
        '- 追加4場の負けはTOPIX22組・NK19組。全41組が1.5ATRの順行に届かず初期損切りとなった。伸びた大きな利益を最後に吐き出したことが、この連続赤字の主因ではない。',
        '- TOPIXの10月5日ナイトは21:55〜翌00:54の9連敗だけで−127,500円。買い・売りを切り替えても短い往復の先で逆行した。小損を許す設計であっても、勝ち波に対し試行回数が多過ぎる。',
        '- TOPIXの10月6日デイは12:35買いを12:54に−12,500円で損切りした後、比較用の「1ATRで切る通常影」が15:35まで継続し、新しい取引を約160分禁止した。12:59:45には同方向の入口信号が再発していた。待機中の上昇は最大22.5pt。通常影を待つ設計が後半の回復参加を妨げたことを確認した。',
        '- 全235組の準備時・約定直前とも、両市場の保持主方向は一致していた。「明示的不一致を無視して注文した」わけではない。ただし保持主方向は最新の勢いとは異なり、追加4場の負け41組中14組で新規開始条件が既に失効していた。',
        '- TOPIXの追加4場は勝ち組率が旧19場39.8%から25.8%へ低下し、平均負け額も15,827円から16,932円へ増えた。NKは44.2%から26.9%へ低下した一方、平均負け額は7,434円から6,684円へ減った。両市場共通の悪化要因は巨大な一撃損ではなく、負けの頻度である。', '',
        '## 改善仮説と反例', '',
        '|仮説|論理的な狙い|確認済みの反例・検証要件|',
        '|---|---|---|',
        '|実口座がフラットになった時点で再評価する|損切りが早くなったのに影時計だけ長く残る不整合を解消する|往復中の再入が増える可能性がある。損切り後の待ち時間・再突破条件を含めて全注文を再生する必要がある|',
        '|主方向の保持だけでなく最近の勢いを確認する|古い方向が残った局面を見送る|旧19場のTOPIX勝ち33組中22組は入口時点で片市場の5分変化が逆向き。押し目成功まで消すため短期逆行の一律禁止は根拠不足|',
        '|同じ価格帯での連敗を検知して再試行を抑える|狭い往復で小損が積み上がるのを防ぐ|単純な当日停止は後半の本流も消す。両市場一致の再突破や一定時間後の復帰を含める必要がある|',
        '|伸びない保有だけ時間経過で撤退・縮小する|1.5ATRに届くまで0.75ATRのリスクを長く残す区間を減らす|追加4場の負けTOPIX22組中9組、NK19組中14組は最大順行0.5ATRすら未達。早い利確だけでは救えない。反対に10/6NKの勝ちは約240分保有しており一律時間切りは長い波を壊し得る|', '',
        'これらは原因から導く検証候補であり、この資料だけで新規則の優位性を証明したものではない。', '',
        '## 追加4場', '', '|セッション|銘柄|組数|勝ち/負け|収支円|負けの1.5ATR未達|始終変化/全値幅|', '|---|---|---:|---:|---:|---:|---:|']
    for r in result['セッション経路']:
        if r['セッション'] in RECENT:
            lines.append(f"|{r['セッション']}|{r['銘柄']}|{r['組数']}|{r['勝ち組数']}/{r['負け組数']}|{r['収支円']:+,.0f}|{r['負け組MFE1_5ATR未達']}|{r['始終変化']:+g}/{r['値幅']:g}|")
    lines += ['', '## 返済理由別の損益（追加4場）', '', '|銘柄|返済理由|利益円|損失円|収支円|', '|---|---|---:|---:|---:|']
    for r in result['原因別']:
        if r['期間'] == '追加4':
            lines.append(f"|{r['銘柄']}|{r['理由']}|{r['利益円']:,.0f}|{r['損失円']:,.0f}|{r['収支円']:+,.0f}|")
    lines += ['', '部分返済を1脚ずつ分ける集計。組単位では途中利確と残り損切りを合算するため、勝ち負け金額は組集計と異なるが収支は一致する。', '',
        '## 各取引', '', '|セッション|銘柄|入口→返済|方向|収支円|MFE/MAE ATR|保有分|出口|開始条件失効|5/15/30分片市場逆行|', '|---|---|---|---|---:|---:|---:|---|---|---|']
    for r in result['全取引']:
        if r['セッション'] in RECENT:
            lines.append(f"|{r['セッション']}|{r['銘柄']}|{r['入口時刻'][11:19]}→{r['返済時刻'][11:19]}|{r['方向']}|{r['収支円']:+,.0f}|{r['MFE_ATR']:.2f}/{r['MAE_ATR']:.2f}|{r['保有分']:.1f}|{r['返済理由']}|{r['開始条件失効']}|" + '/'.join(str(int(r['変化逆行'][str(w)])) for w in (5,15,30))+'|')
    lines += ['', '## 会計と解釈の範囲', '', result['注意']]
    (HERE / '原因の整理.md').write_text('\n'.join(lines)+'\n', encoding='utf8')


if __name__ == '__main__':
    main()
