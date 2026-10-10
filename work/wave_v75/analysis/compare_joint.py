"""前半固定代表を単独対照及び固定遅延の感度と比較する。"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後13', '全29')
REASONS = {1: '初期損切り', 2: 'トレーリング返済', 3: '時間上限返済', 4: '場内全返済', 5: '基準方向の反転'}


def load(path: Path) -> object:
    """機能: 保存済みJSON又は台帳を読み取る。

    引数: path(Path)。返り値: 保存内容(object)。原本を変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 保存入力の内容指紋を計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def deny(*args: object, **kwargs: object) -> None:
    """機能: 保存分析からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('保存分析からの通信は禁止')


def metric(a: dict) -> dict:
    """機能: 一銘柄の利益・損失・平均一取引・活動・気配差を抜き出す。

    引数: a(dict)。返り値: 金額及び件数(dict)。無取引を勝ちに含めない。
    """
    p, loss, count = float(a['profit']), float(a['loss']), int(a['trades'])
    assert abs(p - loss - a['net']) < 1e-5
    return dict(利益=p, 損失=loss, 収支=float(a['net']), 手数料=a['fees'], 取引数=count,
        勝数=a['wins'], 負数=a['losses'], 活動場数=a['active_sessions'], 黒字場数=a['positive_sessions'],
        金額損失割合=loss / (p + loss) if p + loss else None,
        平均一取引収支=a['net'] / count if count else None,
        平均利益=p / a['wins'] if a['wins'] else None,
        平均負け=loss / a['losses'] if a['losses'] else None,
        平均勝負比=a['payoff'], 最大一取引損失=a['max_trade_loss'],
        最大黒字場除外収支=a['without_best_session'], 最大時価下落=a['drawdown'],
        平均保有分=a['hold_seconds'] / count / 60. if count else None,
        気配差負担=a['spread_drag'], 同じ売買時点の中値置換収支=a['net'] + a['spread_drag'])


def compare(joint: dict, single: dict) -> dict:
    """機能: 単独対照に対する総額と一取引平均の改善を分離する。

    引数: joint/single(dict)。返り値: 両方式の指標と差分(dict)。
    相手条件で実際の入口時刻も変わるため、同一機会の因果効果と断定しない。
    """
    j, s = metric(joint), metric(single)
    mean_delta = None if j['平均一取引収支'] is None or s['平均一取引収支'] is None else j['平均一取引収支'] - s['平均一取引収支']
    share_delta = None if j['金額損失割合'] is None or s['金額損失割合'] is None else j['金額損失割合'] - s['金額損失割合']
    loss_delta = j['損失'] - s['損失']
    if not j['取引数']:
        note = '共同案が無取引。損失零を有効な売買の勝利と数えない。'
    elif mean_delta is None:
        note = '対照が無取引のため一取引の改善は比較不能。'
    elif loss_delta < 0 and mean_delta <= 0:
        note = '損失総額は減ったが一取引平均は改善していない。機会削減を含む。'
    elif mean_delta > 0:
        note = '一取引平均が改善。ただし総黒字、金額割合、活動数、前後の一貫性は別に確認する。'
    else:
        note = '一取引平均の改善は確認できない。'
    return dict(共同= j, 単独対照=s, 収支変化=j['収支'] - s['収支'], 利益変化=j['利益'] - s['利益'],
        損失変化=loss_delta, 取引数変化=j['取引数'] - s['取引数'],
        取引削減率=1. - j['取引数'] / s['取引数'] if s['取引数'] else None,
        平均一取引収支変化=mean_delta, 金額損失割合変化=share_delta,
        単純件数換算の損失差=j['損失'] - s['損失'] * j['取引数'] / s['取引数'] if s['取引数'] else None,
        診断=note)


def consistency(joint: dict, single: dict, sessions: list[str], symbol: str) -> dict:
    """機能: 場別とセッション名の日付別に共同と単独の差を比べる。

    引数: joint/single(dict)、sessions(list[str])、symbol(str)。返り値: 一貫性(dict)。
    取引のある場だけの分母も記録し、無取引の同値を改善と数えない。
    """
    j = {a['session']: a for a in joint['rows'] if a['symbol'] == symbol and a['session'] in sessions}
    s = {a['session']: a for a in single['rows'] if a['symbol'] == symbol and a['session'] in sessions}
    assert set(j) == set(s) == set(sessions)
    rows = []
    days = defaultdict(lambda: dict(共同収支=0., 単独収支=0., 共同取引数=0, 単独取引数=0))
    for session in sessions:
        a, b = j[session], s[session]
        rows.append(dict(セッション=session, 共同収支=a['net'], 単独収支=b['net'], 収支差=a['net'] - b['net'],
            共同取引数=a['trades'], 単独取引数=b['trades']))
        day = days[session[:10]]
        for label, value in (('共同収支', a['net']), ('単独収支', b['net']), ('共同取引数', a['trades']), ('単独取引数', b['trades'])):
            day[label] += value
    active = [a for a in rows if a['共同取引数'] or a['単独取引数']]
    day_rows = [dict(日付=day, **a, 収支差=a['共同収支'] - a['単独収支']) for day, a in sorted(days.items())]
    active_days = [a for a in day_rows if a['共同取引数'] or a['単独取引数']]
    positive = [a for a in rows if a['共同収支'] > 0]
    best = max(positive, key=lambda a: (a['共同収支'], a['セッション'])) if positive else None
    total_joint, total_single = sum(a['共同収支'] for a in rows), sum(a['単独収支'] for a in rows)
    return dict(全場数=len(rows), 比較活動場数=len(active), 改善場数=sum(a['収支差'] > 0 for a in active),
        悪化場数=sum(a['収支差'] < 0 for a in active), 同値活動場数=sum(a['収支差'] == 0 for a in active),
        場別差中央値=float(np.median([a['収支差'] for a in active])) if active else None,
        日付定義='セッション名の日付でDayとNightを合算。夜間を実時計の暦日で分割していない。',
        比較活動日数=len(active_days), 改善日数=sum(a['収支差'] > 0 for a in active_days),
        悪化日数=sum(a['収支差'] < 0 for a in active_days),
        日別差中央値=float(np.median([a['収支差'] for a in active_days])) if active_days else None,
        最大共同黒字場=best['セッション'] if best else None,
        同じ最大共同場を除外した共同収支=total_joint - best['共同収支'] if best else total_joint,
        同じ最大共同場を除外した単独収支=total_single - best['単独収支'] if best else total_single,
        場別=rows, 日付別=day_rows)


def exit_groups(archive: dict, sessions: list[str], symbol: str, summary: dict) -> dict:
    """機能: 台帳の全決済を返済理由で分類し、保存済み金額と照合する。

    引数: archive(dict)、sessions(list[str])、symbol(str)、summary(dict)。
    返り値: 返済理由別会計(dict)。返済理由から別出口の因果効果を断定しない。
    """
    groups = defaultdict(list)
    for key, ledger in archive.items():
        if key[0] not in sessions or key[1] != symbol:
            continue
        closes = {int(a[2]): a for a in ledger['orders'] if a[7] == 0}
        for trade in ledger['trades']:
            order = closes[int(trade[0])]
            assert int(order[0]) == int(trade[2])
            groups[int(order[6])].append(float(trade[10]))
    all_net = [value for rows in groups.values() for value in rows]
    assert len(all_net) == summary['trades'] and abs(sum(all_net) - summary['net']) < 1e-5
    assert abs(sum(max(0., a) for a in all_net) - summary['profit']) < 1e-5
    assert abs(sum(max(0., -a) for a in all_net) - summary['loss']) < 1e-5
    return {REASONS.get(code, f'理由{code}'): dict(取引数=len(part), 利益=sum(max(0., a) for a in part),
        損失=sum(max(0., -a) for a in part), 収支=sum(part)) for code, part in sorted(groups.items())}


def check_config(joint: dict, single: dict) -> None:
    """機能: 同じ機構・入口窓・閾値・出口・保有上限の共同対照であることを確認する。

    引数: joint/single(dict)。返り値: なし(None)。不一致では例外を送出する。
    """
    for name in ('family', 'window', 'level', 'hold_seconds', 'width_fraction'):
        assert joint[name] == single[name], (name, joint, single)
    assert joint['paired'] and not single['paired']


def main() -> None:
    """機能: 固定代表が揃った後だけ、共同情報の追加価値と遅延感度を保存する。

    引数: --selection(str)、--delay-dir(list[str]、秒=結果フォルダ)を指定可能。
    返り値: なし(None)。条件や代表を再選定せず、分析領域だけへ書く。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', default='前半選定.json')
    parser.add_argument('--delay-dir', action='append', default=[])
    args = parser.parse_args()
    socket.socket.connect = deny
    socket.create_connection = deny
    selection_path = WORK / args.selection
    fixed_path = WORK / '事前固定.json'
    assert selection_path.exists() and fixed_path.exists(), '事前固定と前半選定が完了してから実行する'
    fixed, selection = load(fixed_path), load(selection_path)
    assert selection['前16だけで選択'] and selection['後13で変更なし']
    primary_paths = sorted((WORK / 'results').glob('*.json'))
    assert len(primary_paths) == 336, '全条件が揃ってから実行する'
    all_results = {a['config']['id']: a for a in (load(p) for p in primary_paths)}
    choices = selection['代表']
    main_values = selection.get('主3', selection.get('上位3', selection.get('主候補', [])))
    main_ids = [a['id'] if isinstance(a, dict) else a for a in main_values]
    delays = {}
    for value in args.delay_dir:
        seconds, path = value.split('=', 1)
        delays[int(seconds)] = Path(path) if Path(path).is_absolute() else WORK / path
    ledgers, paths, representatives = {}, [fixed_path, selection_path, Path(__file__), *primary_paths], {}
    # ----------------------------------------
    # 前半固定代表だけを同一リスクの単独対照と比較し、後半で選び直さない。
    for choice in choices:
        ident = choice['id'] if isinstance(choice, dict) else choice
        joint = all_results[ident]
        c = joint['config']
        assert c['delay'] == 5 and joint['delay'] == 5
        single_id = 'S' + ident[1:]
        single = all_results[single_id]
        check_config(c, single['config'])
        for selected_id in (ident, single_id):
            result_path = WORK / 'results' / (selected_id + '.json')
            ledger_path = WORK / 'ledgers' / (selected_id + '.pkl')
            paths += [result_path, ledger_path]
            ledgers[selected_id] = load(ledger_path)
        periods = {}
        for period in PERIODS:
            periods[period] = {}
            for symbol in SYMBOLS:
                j, s = joint['periods'][period][symbol], single['periods'][period][symbol]
                periods[period][symbol] = dict(**compare(j, s),
                    一貫性=consistency(joint, single, fixed[period], symbol),
                    共同出口理由=exit_groups(ledgers[ident], fixed[period], symbol, j),
                    単独出口理由=exit_groups(ledgers[single_id], fixed[period], symbol, s))
        sensitivity = {}
        for delay, directory in sorted(delays.items()):
            jpath, spath = directory / (ident + '.json'), directory / (single_id + '.json')
            assert jpath.exists() and spath.exists(), ('遅延対照未完了', delay, ident)
            jd, sd = load(jpath), load(spath)
            check_config(jd['config'], sd['config'])
            assert jd['delay'] == sd['delay'] == jd['config']['delay'] == sd['config']['delay'] == delay
            for name in ('family', 'window', 'level', 'hold_seconds', 'width_fraction'):
                assert jd['config'][name] == c[name]
            paths += [jpath, spath]
            sensitivity[str(delay)] = {p: {s: compare(jd['periods'][p][s], sd['periods'][p][s]) for s in SYMBOLS} for p in PERIODS}
        failures = {}
        for symbol in SYMBOLS:
            later = periods['後13'][symbol]['共同']
            reasons = []
            if later['収支'] <= 0:
                reasons.append('後半費用後収支が正でない')
            if later['平均勝負比'] is None or later['平均勝負比'] <= 1:
                reasons.append('後半平均利益対平均負けが一を超えない')
            if later['最大黒字場除外収支'] <= 0:
                reasons.append('後半最大黒字場を除くと黒字でない')
            failures[symbol] = reasons
        representatives[ident] = dict(前半選定=choice, 主候補=ident in main_ids, 固定設定=c,
            後半採用条件の未達内訳=failures,
            単独対照ID=single_id, 単独対照の種類='自価格平均回帰の類似対照。相手条件だけの完全除去ではない。' if int(str(c['signal_id'])[1]) == 4 else '同じ共同観測可能時点で相手価格とOFIの根拠を除去。',
            期間別=periods, 固定遅延感度=sensitivity)
    # ----------------------------------------
    # 全探索の成績分布を示すが、事後の最大収支条件で代表を変更しない。
    distributions = {}
    for paired, label in ((True, '共同168条件'), (False, '単独168条件')):
        subset = [a for a in all_results.values() if a['config']['paired'] == paired]
        assert len(subset) == 168
        distributions[label] = {p: {s: dict(条件数=len(subset),
            黒字数=sum(a['periods'][p][s]['net'] > 0 for a in subset),
            無取引数=sum(a['periods'][p][s]['trades'] == 0 for a in subset)) for s in SYMBOLS} for p in PERIODS}
        for p in PERIODS:
            distributions[label][p]['両銘柄黒字数'] = sum(all(a['periods'][p][s]['net'] > 0 for s in SYMBOLS) for a in subset)
    output = dict(代表変更なし=True, 条件追加なし=True, API取得数=0, 実注文数=0,
        分離='取引数削減、平均一取引、損失金額割合、場と日付の一貫性を別集計。単純件数換算は説明用で因果効果ではない。',
        同期限界='CurrentPriceTimeは最終約定の代理時計。遅延付きstrict asofでも実受信順の証明にはならない。短い遅延だけの成功を実行可能な先回りと呼ばない。',
        遅延解釈='前半固定の同じ機構・窓・閾値・出口・保有上限を遅延だけ変更。最良遅延への選び直しなし。',
        中値置換='保存済み売買行を中値へ置換する説明用感度。入口・出口を再実行した実行可能成績ではない。',
        既知期間='前16選定・後13固定確認。ただし以前の探索で知られた29場であり完全未知の将来検証とは呼ばない。',
        全336の分布=distributions, 主候補ID=main_ids, 固定代表=representatives,
        感度取得済み遅延=sorted(delays), 入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))})
    target = HERE / '二指数情報の追加価値と遅延感度.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(照合合格=True, 条件数=len(all_results), 固定代表数=len(representatives), 感度遅延=sorted(delays)), ensure_ascii=False))


if __name__ == '__main__':
    main()
