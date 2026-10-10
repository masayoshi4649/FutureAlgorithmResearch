"""固定した20条件を、保存済み原本の順序だけで検証する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute, REASONS
from signals import methods, decisions
from features import load_inputs_only


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = ROOT / 'アルゴリズム調査/00052_ATRを使わない単純手法'
spec = importlib.util.spec_from_file_location('export55', HERE.parent / 'wave_v52/export.py')
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


def clean(value: object) -> object:
    """機能: 不明値をJSONのnullへ変換し、NaNを公開資料へ混入させない。

    引数: value(object)。返り値: 有限JSONに格納可能な値(object)。
    """
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def freeze(configs: list) -> None:
    """機能: 最初の損益計算前に条件と実行コードを固定する。

    引数: configs(list)。返り値: なし(None)。固定後の無記録変更は拒否する。
    """
    hashes = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
              for name in ('signals.py', 'engine.py', 'features.py', 'backtest.py')}
    path = HERE / '売買仕様固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8'))['コードSHA256'] == hashes, '固定後の変更です'
        return
    save(path, dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 条件=configs, コードSHA256=hashes,
                    仮説='入口を単純な価格条件に絞り、初回から同じ幅で追跡するだけで、両市場で損小利大が成立するか。',
                    禁止='ATRを計算、準備判定、入口、保有、出口、診断単位のいずれにも使用しない。板ゲート、銘柄別閾値、先の足、場を跨ぐ保有も使用しない。',
                    共通準備='当場20分経過、現在を含む連続20分確定足と価格鮮度。P04は現在を除く過去20分も必要。',
                    初回='P01/P02/P05は初回準備時に条件が既成立なら状態参入を一度許す。以降は新しい交差だけ。保有や休止で無効でも機会を消費する。',
                    始値='当場で最初に観測した有効原本行の最終価格。公式始値と同じとは限らない。',
                    入口='確定1分中値足を次分の最初の有効原本行で公開。P01始値±0.10%の外向き交差。P02BB20±2σの外向き交差。P03前足帯外から現足が両帯内へ復帰し逆向き。P04現在足除外20分高安越え。P05EMA8/21交差。',
                    幅='当場の観測始値0.05/0.10/0.20%又は判断時20分終値の母標準偏差1倍。2呼値以上で呼値単位切上げ。判断時に固定し保有中に変えない。',
                    保有='初期逆指値も最良価格からの追跡も同じ幅。約定直後から全原本行で追跡。利確目標・時間切れ・反対信号による決済・追加・半減なし。',
                    実行='判断後の次の有効原本行の最終価格で約定。費用0。TOPIXmini5枚/NK225micro10枚、片方向上限10/20以内。',
                    場内='Day15:35/Night翌05:50で返済判断。最後5分は新規判断しない。全返済後60秒休止。',
                    評価='利益/損失/収支、勝ち負け返済枚数、1枚平均利益/損失比、最大利益場除外、前10/次9/後4場を各銘柄で別評価。',
                    候補基準='各銘柄で収支と最大利益場除外収支が正、1枚平均勝ち/負け>1、3期間とも黒字、30組以上/活動8場以上。これは統計的有意性の証明ではない。',
                    限界='既に研究に使った23場。今回の条件を先に固定しても未知期間検証にはならない。旧研究との差は入口・出口も異なり、ATRだけの因果効果とは扱わない。',
                    現在API取得数=0))


def summarize(accounts: list[dict]) -> dict:
    """機能: 金額、決済枚数、初期幅単位、保有時間を同銘柄内で集計する。

    引数: accounts(list[dict])。返り値: 集計(dict)。
    """
    out = export.summarize(accounts)
    groups = np.asarray([g for a in accounts for g in a['width_groups']], float).reshape(-1, 9)
    legs = np.asarray([t for a in accounts for t in a['trades']], float).reshape(-1, 16)
    ws = groups[:, 2]
    wins, losses = ws[ws > 0], -ws[ws < 0]
    out.update(w_net=float(ws.sum()), w_mean=float(ws.mean()) if len(ws) else None,
               w_payoff=float(wins.mean() / losses.mean()) if len(wins) and len(losses) else None,
               w_without_best=float(ws.sum() - max([a['w_net'] for a in accounts], default=0)),
               median_hold_minutes=float(np.median(legs[:, 15])) if len(legs) else None,
               median_width=float(np.median(groups[:, 1])) if len(groups) else None,
               mean_mfe_width=float(groups[:, 7].mean()) if len(groups) else None,
               mean_mae_width=float(groups[:, 8].mean()) if len(groups) else None)
    out['base_pass'] = bool(out['net'] > 0 and out['without_best'] > 0 and out['payoff'] is not None
                            and out['payoff'] > 1 and out['cycles'] >= 30 and out['active_sessions'] >= 8)
    return out


def week(session: str) -> str:
    """機能: 開始日を月曜起点の週へ分ける。

    引数: session(str)。返り値: 週開始日(str)。
    """
    day = datetime.strptime(session[:10], '%Y-%m-%d')
    return (day - timedelta(days=day.weekday())).date().isoformat()


def ledger(account: dict) -> list[dict]:
    """機能: 判断・約定時刻と行番号、固定幅、全決済損益を出力する。

    引数: account(dict)。返り値: 台帳行(list[dict])。
    """
    return [dict(判断時刻=export.stamp(o[0]), 約定時刻=export.stamp(o[1]), 判断原本行=int(o[2]), 約定原本行=int(o[3]),
                 区分='新規' if o[4] == 1 else '返済', 方向='買い' if o[5] > 0 else '売り', 枚数=int(o[6]),
                 価格=o[7], 収支円=o[8], 理由=REASONS[int(o[9])], 組=int(o[10]), 固定幅=o[12])
            for o in account['orders']]


def main() -> None:
    """機能: 20条件を固定後に全保存場へ適用し、後から条件を追加しない。

    引数: なし。返り値: なし(None)。
    """
    configs = methods()
    freeze(configs)
    features = pickle.loads((HERE / '特徴.pkl').read_bytes())
    inputs = load_inputs_only()
    assert set(features) == set(inputs)
    sessions = sorted({k[0] for k in inputs})
    output, session_rows, week_rows, signal_map = [], [], [], {}
    for config in configs:
        accounts = []
        for key in sorted(inputs):
            qty, value = (5, 1000) if key[1] == 'TOPIX' else (10, 10)
            signals = decisions(features[key], config['family'], config['width'], inputs[key]['tick'])
            signal_map[(key, config['id'])] = signals
            a = execute(inputs[key], signals, qty, value)
            a['intervals'] = export.intervals(inputs[key], a)
            a['candidate_count'] = len(signals)
            accounts.append(a)
            assert a['win_qty'] + a['loss_qty'] + a['flat_qty'] == a['cycles'] * qty
            export.save_csv(HERE / '台帳' / config['id'] / f'{key[0]}_{key[1]}.csv', ledger(a))
            session_rows.append(dict(手法=config['id'], セッション=key[0], 銘柄=key[1], 利益円=a['profit'], 損失円=a['loss'],
                                     収支円=a['net'], 利益枚数=a['win_qty'], 損失枚数=a['loss_qty'], 同値枚数=a['flat_qty'],
                                     枚数差=a['win_qty']-a['loss_qty'], 取引組数=a['cycles'], 初期幅単位損益=a['w_net']))
        summary, weeks, periods = {}, {}, {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [a for a in accounts if a['symbol'] == symbol]
            summary[symbol] = summarize(selected)
            weeks[symbol] = {w: summarize([a for a in selected if week(a['session']) == w])
                             for w in sorted({week(s) for s in sessions})}
            periods[symbol] = {name: summarize([a for a in selected if a['session'] in keys])
                               for name, keys in [('前10場', sessions[:10]), ('次9場', sessions[10:19]), ('後4場', sessions[19:])]}
            summary[symbol]['period_pass'] = all(v['net'] > 0 for v in periods[symbol].values())
            summary[symbol]['candidate_pass'] = summary[symbol]['base_pass'] and summary[symbol]['period_pass']
            for w, a in weeks[symbol].items():
                week_rows.append(dict(手法=config['id'], 週開始=w, 銘柄=symbol, 利益円=a['profit'], 損失円=a['loss'], 収支円=a['net'],
                                      利益枚数=a['win_qty'], 損失枚数=a['loss_qty'], 同値枚数=a['flat_qty'],
                                      枚数差=a['win_qty']-a['loss_qty'], 取引組数=a['cycles']))
        compact = [{k: v for k, v in a.items() if k not in ('curve', 'w_curve')} for a in accounts]
        output.append(dict(**config, accounts=compact, summary=summary, weeks=weeks, periods=periods))
        print(config['id'], [(s, summary[s]['net'], summary[s]['cycles'], round(summary[s]['payoff'] or 0, 3))
                             for s in ('TOPIX', 'NK225')], flush=True)
    # ----------------------------------------
    # 保存物は過去研究と分け、全条件の成績を残す。
    (HERE / '判断.pkl').write_bytes(pickle.dumps(signal_map, pickle.HIGHEST_PROTOCOL))
    export.save_csv(REPORT / 'セッション別損益.csv', session_rows)
    export.save_csv(REPORT / '週別損益.csv', week_rows)
    save(HERE / '売買結果.json', dict(methods=output, sessions=sessions,
                                      meta=dict(conditions=20, accounts=20 * len(inputs), qty='TOPIXmini5枚/NK225micro10枚、追加なし',
                                                scope='保存済み2026-09-21〜2026-10-06の23場', current_api_requests=0, unseen=False,
                                                common_candidates=[m['id'] for m in output if all(m['summary'][s]['candidate_pass'] for s in ('TOPIX', 'NK225'))])))


if __name__ == '__main__':
    main()
