"""固定代表の休止効果、方向対照、入口位置と直近進行を分離して集計する。"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後13', '全29')
PAUSES = ('休止なし', '二敗十分', '二敗三十分', '二敗収束待ち', '二敗十分かつ収束', '三敗三十分')
REASONS = {1: '初期損切り', 2: 'トレーリング返済', 3: '六十分返済判断', 4: '場内全返済', 5: '基準方向の反転'}
ZONE = timezone(timedelta(hours=9))


def load(path: Path) -> object:
    """機能: 保存済みの固定結果又は原本準備配列を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。読取以外は行わない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def save(name: str, value: object) -> None:
    """機能: 分析担当領域だけへ日本語の検査証跡を保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    target = (HERE / name).resolve()
    assert target.is_relative_to(HERE)
    HERE.mkdir(exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 分析に用いた固定ファイルの内容指紋を得る。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def metric(a: dict) -> dict:
    """機能: 費用後の金額、平均一取引、活動数、休止、再開後を表示用に抜き出す。

    引数: a(dict)。返り値: 金額と活動の指標(dict)。
    """
    p, loss, count = a['profit'], a['loss'], a['trades']
    assert abs(p - loss - a['net']) < 1e-5
    return dict(利益=p, 損失=loss, 収支=a['net'], 手数料=a['fees'],
        金額損失割合=loss / (p + loss) if p + loss else None,
        取引数=count, 勝数=a['wins'], 負数=a['losses'],
        平均一取引収支=a['net'] / count if count else None,
        平均利益=p / a['wins'] if a['wins'] else None,
        平均負け=loss / a['losses'] if a['losses'] else None,
        平均勝負比=a['payoff'], 最大一取引損失=a['max_trade_loss'],
        活動場数=a['active_sessions'], 黒字場数=a['positive_sessions'],
        最大黒字場除外収支=a['without_best_session'], 最大時価下落=a['drawdown'],
        休止回数=a['pause_count'], 復帰回数=a['resume_count'], 休止秒=a['paused_seconds'],
        復帰後取引数=a['resumed_trades'], 復帰後収支=a['resumed_net'],
        復帰後平均収支=a['resumed_net'] / a['resumed_trades'] if a['resumed_trades'] else None,
        平均保有秒=a['hold_seconds'] / count if count else None,
        気配差悪化=a['spread_drag'], 参照値欠測場数=a['missing_reference_sessions'])


def pause_comparison(base: dict, target: dict) -> dict:
    """機能: 総損失減少と一取引の改善を分け、取引減少の比率を記録する。

    引数: base/target(dict)は休止なしと同じ基準・入口・幅の休止あり。
    返り値: 変化と限定付きの診断(dict)。予測力の統計的証明は行わない。
    """
    b, a = metric(base), metric(target)
    reduction = b['取引数'] - a['取引数']
    mean_delta = None if b['平均一取引収支'] is None or a['平均一取引収支'] is None else a['平均一取引収支'] - b['平均一取引収支']
    loss_delta = a['損失'] - b['損失']
    if not a['取引数']:
        note = '無取引。損失ゼロを売買の成功又は勝利と数えない。'
    elif loss_delta < 0 and mean_delta is not None and mean_delta <= 0:
        note = '総損失は減ったが、一取引平均は改善しない。取引数や露出の減少を含む。'
    elif loss_delta < 0 and mean_delta is not None and mean_delta > 0:
        note = '総損失と一取引平均は改善。ただし入口時刻も変わるため、休止の予測力を証明したとはしない。'
    elif mean_delta is not None and mean_delta > 0:
        note = '一取引平均は改善したが、総損失は減っていない。'
    else:
        note = 'この期間では休止なしより明確な改善を確認できない。'
    return dict(**a, 削減取引数=reduction,
        取引削減率=reduction / b['取引数'] if b['取引数'] else None,
        利益変化=a['利益'] - b['利益'], 損失変化=loss_delta,
        収支変化=a['収支'] - b['収支'], 平均一取引収支変化=mean_delta,
        金額損失割合変化=None if a['金額損失割合'] is None or b['金額損失割合'] is None else a['金額損失割合'] - b['金額損失割合'],
        同数取引へ単純換算した損失=loss_delta if not b['取引数'] else a['損失'] - b['損失'] * a['取引数'] / b['取引数'],
        診断=note)


def historical(times: np.ndarray, broken: np.ndarray, seconds: float) -> np.ndarray:
    """機能: 品質リセットと時計逆行で分けた履歴から指定秒以前の最後の行を得る。

    引数: times(ndarray)、broken(ndarray[bool])、seconds(float)。
    返り値: 参照行(ndarray[int64])。現在行以後及び区間外を参照しない。
    """
    out = np.full(len(times), -1, dtype=np.int64)
    breaks = np.asarray(broken, dtype=bool).copy()
    if len(times):
        breaks[0] = True
        breaks[1:] |= times[1:] < times[:-1]
    starts = np.flatnonzero(breaks)
    ends = np.r_[starts[1:], len(times)]
    for start, end in zip(starts, ends):
        segment = times[start:end]
        j = np.searchsorted(segment, segment - seconds, side='right') - 1
        available = j >= 0
        out[start:end][available] = start + j[available]
    have = out >= 0
    assert np.all(out[have] < np.flatnonzero(have))
    assert np.all(times[out[have]] <= times[have] - seconds)
    return out


def sign(value: float) -> int:
    """機能: 有効な価格差を方向符号にする。

    引数: value(float)。返り値: 正一、負一、等値零(int)。
    """
    return 1 if value > 0 else -1 if value < 0 else 0


def current_labels(i: int, side: int, c: dict, r: dict, refs: dict, lag: np.ndarray) -> dict:
    """機能: 発注判断行までの価格と既知基準だけから位置・直近進行を分類する。

    引数: i/side(int)、c/r/refs(dict)、lag(ndarray[int64])。
    返り値: 入口時点のラベル(dict)。返済行、返済価格、将来最大値は引数に取らない。
    """
    last, stamp = float(r['last'][i]), float(r['time_s'][i])
    op, prev = refs['ref_open'], refs['ref_prev']
    assert i >= op['known_from_i'] and op['source_time'] <= stamp and op['source_seq'] <= r['seq'][i]
    open_gap = last - op['value']
    prev_gap = None
    if prev['value'] is not None and i >= prev['known_from_i']:
        assert prev['source_time'] < r['start'] and prev['source_time'] <= stamp
        prev_gap = last - prev['value']
    j = int(lag[i])
    change = None if j < 0 else last - float(r['last'][j])
    movement = None if change is None else sign(change)
    if prev_gap is None:
        label = '前保存終値欠測'
    elif change is None:
        label = '六十秒履歴未準備'
    elif prev_gap > 0 and change < 0:
        label = '前保存終値より上だが直近下落'
    elif prev_gap < 0 and change > 0:
        label = '前保存終値より下だが直近上昇'
    elif change == 0:
        label = '直近変化なし'
    elif prev_gap == 0:
        label = '前保存終値と等値'
    else:
        label = '前保存終値の位置と直近進行が一致'
    if change is None:
        open_label = '六十秒履歴未準備'
    elif sign(open_gap) * movement < 0:
        open_label = '始値の位置と直近進行が不一致'
    elif change == 0 or open_gap == 0:
        open_label = '始値等値又は直近変化なし'
    else:
        open_label = '始値の位置と直近進行が一致'
    a = sign(open_gap) if abs(open_gap) > op['value'] * c['band'] else 0
    b = sign(prev_gap) if prev_gap is not None and abs(prev_gap) > prev['value'] * c['band'] else 0
    mode = c['reference']
    d = a if mode == 0 else b if mode == 1 else a if mode == 2 and a == b else 0
    if mode == 3 and j >= 0:
        price = float(r['last'][j])
        d = sign(change) if abs(change) > price * c['band'] else 0
    if c['inverse']:
        d = -d
    assert d == side, ('判断時許可方向の不一致', c['id'], i, d, side)
    return dict(判断行=i, 判断連番=int(r['seq'][i]), 判断時計=datetime.fromtimestamp(stamp, ZONE).isoformat(),
        判断価格=last, 判断時許可方向=d, 始値=op['value'], 始値差=open_gap,
        始値既知開始行=op['known_from_i'], 始値由来=op['kind'],
        前保存終値=prev['value'], 前保存終値差=prev_gap, 前保存終値由来=prev['kind'],
        六十秒前行=j, 六十秒前連番=None if j < 0 else int(r['seq'][j]),
        過去参照経過秒=None if j < 0 else stamp - float(r['time_s'][j]),
        直近価格変化=change, 前値位置進行ラベル=label, 始値位置進行ラベル=open_label,
        建玉方向進行ラベル='六十秒履歴未準備' if movement is None else '直近変化なし' if movement == 0 else '建玉と同方向の直近進行' if side == movement else '建玉と逆方向の直近進行',
        時間帯=f'{datetime.fromtimestamp(stamp, ZONE).hour:02}時台')


def money(rows: list[dict]) -> dict:
    """機能: ラベル群の費用後損益、料金起因損失、出口理由を集計する。

    引数: rows(list[dict])は検証専用の入口ラベルと後続決済結果。
    返り値: 全損失を含む群会計(dict)。無取引は勝ちと扱わない。
    """
    p = sum(max(0., r['収支']) for r in rows)
    loss = sum(max(0., -r['収支']) for r in rows)
    wins = sum(r['収支'] > 0 for r in rows)
    losses = sum(r['収支'] < 0 for r in rows)
    reasons = {}
    for code, name in REASONS.items():
        subset = [r for r in rows if r['出口理由番号'] == code]
        reasons[name] = dict(取引数=len(subset), 損失=sum(max(0., -r['収支']) for r in subset),
                            収支=sum(r['収支'] for r in subset))
    return dict(取引数=len(rows), 勝数=wins, 負数=losses, 利益=p, 損失=loss, 収支=p - loss,
        金額損失割合=loss / (p + loss) if p + loss else None,
        平均一取引収支=(p - loss) / len(rows) if rows else None,
        平均負け=loss / losses if losses else None,
        最大一取引損失=max((max(0., -r['収支']) for r in rows), default=0.),
        料金だけで赤字の数=sum(r['料金前損益'] >= 0 and r['収支'] < 0 for r in rows),
        料金だけで赤字の損失=sum(-r['収支'] for r in rows if r['料金前損益'] >= 0 and r['収支'] < 0),
        手数料=sum(r['手数料'] for r in rows), 出口理由=reasons)


def group_money(rows: list[dict], field: str) -> dict:
    """機能: 当時ラベル、時刻、又は場別に群を作り、金額を相殺せず記録する。

    引数: rows(list[dict])、field(str)。返り値: 各群の会計(dict)。
    """
    groups = defaultdict(list)
    for r in rows:
        groups[r[field]].append(r)
    return {name: money(part) for name, part in sorted(groups.items())}


def reference_evidence(meta: dict) -> dict:
    """機能: 参照価格の既知開始・代替・欠測・週末を損益と独立に残す。

    引数: meta(dict)。返り値: 定義と全口座の参照由来(dict)。
    """
    return dict(定義=meta['definitions'], 数量=meta['counts'],
        全場原本指紋一致=meta['全場原本指紋一致'], 未来補完なし=meta['未来補完なし'],
        参照価格=meta['references'],
        注意='観測始値に代替した口座がある。前保存場の最終観測値と公式前日終値は別。本人の取得価格や損切り注文は観測できない。')


def deny(*args: object, **kwargs: object) -> None:
    """機能: 分析のネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存分析からの通信は禁止')


def main() -> None:
    """機能: 固定前半選定が揃ってから同設定の対照と入口ラベルを独立分析する。

    引数: なし。返り値: なし(None)。入口条件、選定、原本、既存成果は変更しない。
    """
    sys.dont_write_bytecode = True
    socket.socket.connect = deny
    socket.create_connection = deny
    assert (WORK / '前半選定.json').exists(), '前半選定完了後に実行する'
    assert len(list((WORK / 'results').glob('*.json'))) == 480, '全固定結果が揃ってから実行する'
    fixed, selected, meta = (load(WORK / name) for name in ('事前固定.json', '前半選定.json', 'inputs/refmetadata.json'))
    assert selected['前16だけで選択'] and selected['後13で変更なし']
    ready, features = {}, {}
    for label, target in (('ready', ready), ('features', features)):
        for path in meta['input_paths'][label]:
            part = load(ROOT / path)
            assert not set(target) & set(part)
            target.update(part)
    assert set(ready) == set(features) and len(ready) == 58
    lags = {}
    for key, r in ready.items():
        f = features[key]
        quality = f['valid'] & np.isfinite(f['bid']) & np.isfinite(f['ask']) & (f['bid'] > 0) & (f['ask'] > f['bid']) & (f['ask'] - f['bid'] <= 2 * r['tick'] + r['tick'] * 1e-8)
        lags[key] = historical(r['time_s'], f['reset'] | ~quality, 60.)
    results, ledgers, used_paths, details, choices, examples = {}, {}, [], [], {}, []

    def result(ident: str) -> dict:
        """機能: 固定された指定IDだけを読み、同じ比較ファイルを再読しない。

        引数: ident(str)。返り値: 保存会計(dict)。
        """
        if ident not in results:
            path = WORK / 'results' / (ident + '.json')
            results[ident] = load(path)
            used_paths.append(path)
        return results[ident]

    def labels(ident: str) -> list[dict]:
        """機能: 指定条件の入口時点の因果ラベルへ、検証専用の後続決済を接続する。

        引数: ident(str)。返り値: 全場の検証明細(list[dict])。
        """
        if ident in ledgers:
            return ledgers[ident]
        data = result(ident)
        c = data['config']
        path = WORK / 'ledgers' / (ident + '.pkl')
        archive = load(path)
        used_paths.append(path)
        records = []
        for key, ledger in sorted(archive.items()):
            r, refs = ready[key], meta['references']['|'.join(key)]
            opens = {int(o[2]): o for o in ledger['orders'] if o[7] == 1}
            closes = {int(o[2]): o for o in ledger['orders'] if o[7] == 0}
            for trade in ledger['trades']:
                cid = int(trade[0])
                source, exit_order = opens[cid], closes[cid]
                i, fill_i, exit_i, side = int(source[1]), int(trade[1]), int(trade[2]), int(trade[3])
                assert i < fill_i <= exit_i and int(source[0]) == fill_i and int(exit_order[0]) == exit_i
                label = current_labels(i, side, c, r, refs, lags[key])
                records.append(dict(**label, ID=ident, セッション=key[0], 銘柄=key[1], 取引番号=cid,
                    新規行=fill_i, 返済行=exit_i, 建玉方向=side, 枚数=int(trade[4]),
                    新規価格=float(trade[5]), 返済価格=float(trade[6]),
                    手数料=float(trade[7] + trade[8]), 料金前損益=float(trade[9]), 収支=float(trade[10]),
                    出口理由番号=int(exit_order[6]), 出口理由=REASONS[int(exit_order[6])],
                    保有秒=float(r['time_s'][exit_i] - r['time_s'][fill_i])))
        for period in PERIODS:
            for symbol in SYMBOLS:
                part = [a for a in records if a['銘柄'] == symbol and a['セッション'] in fixed[period]]
                a = money(part)
                b = data['periods'][period][symbol]
                assert a['取引数'] == b['trades']
                assert abs(a['利益'] - b['profit']) < 1e-5 and abs(a['損失'] - b['loss']) < 1e-5
        ledgers[ident] = records
        details.extend(records)
        return records

    # ----------------------------------------
    # 選定代表を差し替えず、同じ基準と入口と幅の休止六案・方向四案を比較する。
    for choice in selected['代表']:
        ident = choice['id']
        main_result = result(ident)
        c = main_result['config']
        stem = ident.rsplit('_P', 1)[0]
        pause_ids = [stem + '_P' + str(j) for j in range(6)]
        base_id = pause_ids[0]
        suffix = f"_E{c['entry_type']}_B{0 if c['band'] == 0 else 1}_W{int(c['width_fraction'] * 10000):02}_P0"
        controls = {'同方向の主案': base_id, '基準と逆方向': f"X{c['reference']}" + suffix,
                    '跨ぎ返済なし': f"K{c['reference']}" + suffix, '六十秒方向': 'M3' + suffix}
        pcompare = {period: {symbol: [] for symbol in SYMBOLS} for period in PERIODS}
        ccompare = {period: {symbol: {} for symbol in SYMBOLS} for period in PERIODS}
        for pause, pid in enumerate(pause_ids):
            target = result(pid)
            for name in ('reference', 'entry_type', 'band', 'width_fraction', 'inverse', 'exit_on_reverse'):
                assert target['config'][name] == c[name]
            for period in PERIODS:
                for symbol in SYMBOLS:
                    a = pause_comparison(result(base_id)['periods'][period][symbol], target['periods'][period][symbol])
                    pcompare[period][symbol].append(dict(ID=pid, 休止方式=PAUSES[pause], **a))
        for label, cid in controls.items():
            target = result(cid)
            for period in PERIODS:
                for symbol in SYMBOLS:
                    ccompare[period][symbol][label] = dict(ID=cid, **metric(target['periods'][period][symbol]))
        diagnostic = {}
        for lid in dict.fromkeys([ident, *controls.values()]):
            records = labels(lid)
            diag = {}
            for period in PERIODS:
                diag[period] = {}
                for symbol in SYMBOLS:
                    part = [a for a in records if a['銘柄'] == symbol and a['セッション'] in fixed[period]]
                    diag[period][symbol] = dict(全取引=money(part),
                        前保存終値位置と進行=group_money(part, '前値位置進行ラベル'),
                        始値位置と進行=group_money(part, '始値位置進行ラベル'),
                        建玉方向と進行=group_money(part, '建玉方向進行ラベル'),
                        時間帯=group_money(part, '時間帯'), セッション=group_money(part, 'セッション'))
            diagnostic[lid] = diag
        chosen = labels(ident)
        scene = defaultdict(list)
        for record in chosen:
            scene[(record['セッション'], record['銘柄'])].append(record)
        ranked = [(money(part)['収支'], key, part) for key, part in scene.items() if money(part)['収支'] < 0]
        if ranked:
            _, key, part = min(ranked, key=lambda x: (x[0], x[1]))
            losing = min(part, key=lambda x: (x['収支'], x['取引番号']))
            examples.append(dict(ID=ident, 選び方='当該前半選定代表の全二十九場中、銘柄別で赤字最大の場。その場の最大負け一取引を併記。再選定には使わない。',
                セッション=key[0], 銘柄=key[1], 場会計=money(part), 最大負けの当時ラベルと後続結果=losing))
        choices[ident] = dict(前半選定=choice, 固定設定=c, 休止比較=pcompare,
            方向と返済の対照=ccompare, 入口位置と進行の診断=diagnostic)
    # ----------------------------------------
    # 未来の決済金額は採点専用であり、入口や休止解除へ戻さない。
    header = dict(選定変更なし=True, 追加条件なし=True, API取得数=0, 実注文数=0,
        位置ラベル='新規の発注判断行までのCurrentPriceと品質リセットを跨がない六十秒以前の価格、当時既知の始値と前保存場最終価格で判定。',
        未来ラベルの隔離='返済金額と出口理由は診断の採点専用。入口条件、方向配列、休止解除、代表選定へ戻さない。',
        休止の解釈='休止で再入場時刻も変わる。総損失減少、一取引平均改善、復帰後成績を分ける。単純な件数換算は説明用の分解で、同一機会の因果対照又は予測力の証明ではない。',
        方向対照の解釈='六十秒方向は固定基準を外した別入口。完全に同じ入口候補を方向フィルターだけ外した対照ではない。',
        心理の解釈='保存板と約定価格から参加者本人の取得原価や心理を直接証明しない。既知期間の再探索であり未知市場の収益性の証明ではない。')
    paths = [WORK / '事前固定.json', WORK / '前半選定.json', WORK / 'inputs/refmetadata.json', Path(__file__), *used_paths]
    output = dict(**header, 代表=choices, 顕著な赤字場三例=examples, 参照価格証跡=reference_evidence(meta),
                  入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))})
    save('基準制限と休止の効果分析.json', output)
    save('入口位置と進行の診断明細.json', dict(**header, 明細数=len(details), 明細=details))
    print(json.dumps(dict(全合格=True, 代表=list(choices), 診断明細数=len(details), 原因例数=len(examples)), ensure_ascii=False))


if __name__ == '__main__':
    main()
