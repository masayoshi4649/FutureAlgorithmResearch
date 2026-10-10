"""損益を見る前に固定した補充監視12条件を、全保存原本で検証する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute, REASONS
from signals import methods, decisions, candidates


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = ROOT / 'アルゴリズム調査/00054_補充監視3手法の実装とセッション損益'
spec = importlib.util.spec_from_file_location('export57', HERE.parent / 'wave_v52/export.py')
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
    hashes['../wave_v56/measurement/display_changes.py'] = hashlib.sha256(
        (HERE.parent / 'wave_v56/measurement/display_changes.py').read_bytes()).hexdigest()
    path = HERE / '売買仕様固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8'))['コードSHA256'] == hashes, '固定後の変更です'
        return
    save(path, dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), 条件=configs, コードSHA256=hashes,
                    入力SHA256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in ('features.pkl', 'events.pkl')},
                    仮説='同価格の表示数量の減少と回復を追跡し、その後の反転・突破・補充位置移動を取ることで両市場に共通する利益が得られるか。',
                    禁止='ATR、機械学習、銘柄別閾値、先の行、場を跨ぐ保有を使用しない。同一主体・隠れ注文・真の売買主体は識別できない。',
                    共通準備='当場120秒経過、完全かつ順序正常な10段板。時刻は約定時計で受信時計ではない。raw行数は同じ時計値の行も含む。',
                    補充='同価格の既知減少を蓄積し、その80%以上かつ開始直前の同側最良数量の25%以上を回復すると1周期完了。減少分を上限に回復量を計上。30秒または500raw行超過で破棄。最良消失再出現の既知0は含め、遠方10段外は未知として履歴を破棄。',
                    壁='同価格の完了が120秒かつ2000raw行以内で2回または3回に初めて達し、その価格が現在最良にある時だけ認定。板不正・原本不連続・時計逆行・出来高リセットで状態消去。',
                    執行代理='売買代金増分を出来高増分とラージ倍率で除した平均値を、直前気配と比較。ask以上は買い、bid以下は売り、気配内は不明。真の発注方向ではない。',
                    始値='当場で最初に観測した有効原本行の最終価格。公式始値と同じとは限らない。',
                    入口R1='買い:bid壁認定時の過去30秒売り代理>0かつ買い以上。その後120秒/2000行以内にbidが壁より1呼値以上上、中値が認定時より1呼値以上上、過去10秒買い代理>=売り代理かつ合計>0。bidが壁より下なら待機破棄。売りは対称。',
                    入口R2='買い:ask壁認定時の過去30秒買い代理>0かつ売り以上。その後ask>壁かつbid>=壁が2約定時計秒継続し、当該壁の最終補充完了から3秒以上。崩れた1行で継続時計をリセット。売りは対称。',
                    入口R3='買い:前の認定bid壁から120秒/2000raw行以内に、新しい認定bid壁が1呼値以上上がり、askも前の認定時から1呼値以上上がる。売りは対称。',
                    機会消費='壁の条件到達時だけ認定し、その時点で代理圧力不足ならR1/R2は後から同じ認定を再利用しない。保有や休止で無効でも入口を消費。同一行で相反する同類型の入口は両方見送り。',
                    幅='当場の観測始値0.05/0.10%、2ラージ呼値以上で呼値単位切上げ。判断時に固定。主条件は補充2回/0.05%で成績後に変更しない。',
                    保有='新規約定行の中値を高安追跡の初期値とし、全有効原本行の中値で一定幅トレーリング。構造逆指値は買いで壁1呼値下、売りで壁1呼値上。二つの線の有利側で全返済。利確目標・反対信号返済・追加・半減なし。',
                    実行='判断後の次の有効原本行の最終価格で約定。費用0。TOPIXmini5枚/NK225micro10枚、片方向上限10/20以内。',
                    価格感度='全条件で、同じ注文行の中値、および買ask/売bidへ再評価する。入口・出口経路は約定lastを参照せず、この再評価は同条件の再生と同値。最終約定価格だけ黒字でも有望と結論しない。',
                    場内='Day15:35/Night翌05:50で返済判断。最後5分は新規判断しない。全返済後60秒休止。',
                    評価='利益/損失/収支、勝ち負け返済枚数、1枚平均利益/損失比、最大利益場除外、前10/次9/後4場を各銘柄で別評価。',
                    候補基準='各銘柄で収支と最大利益場除外収支が正、1枚平均勝ち/負け>1、3期間とも黒字、30組以上/活動8場以上。これは統計的有意性の証明ではない。',
                    限界='既に研究に使った23場。今回の条件を先に固定しても未知期間検証にはならない。12条件は感度比較であり、補充が利益原因かの対照実験ではない。',
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
    """機能: 12条件を固定後に全保存場へ適用し、後から条件を追加しない。

    引数: なし。返り値: なし(None)。
    """
    configs = methods()
    freeze(configs)
    features = pickle.loads((HERE / 'features.pkl').read_bytes())
    events = pickle.loads((HERE / 'events.pkl').read_bytes())
    inputs = pickle.loads((HERE.parent / 'wave_v55/clean_inputs.pkl').read_bytes())
    assert set(features) == set(inputs)
    sessions = sorted({k[0] for k in inputs})
    output, session_rows, week_rows, signal_map, candidate_map = [], [], [], {}, {}
    for key in sorted(inputs):
        np.testing.assert_array_equal(inputs[key]['seq'], features[key]['seq'])
        for count in (2, 3):
            candidate_map[(key, count)] = candidates(features[key], events[key], count, inputs[key]['tick'], inputs[key]['start'])
        print('入口判定', key, {c: {f: len(v) for f, v in candidate_map[(key, c)].items()} for c in (2, 3)}, flush=True)
    (HERE / '入口候補.pkl').write_bytes(pickle.dumps(candidate_map, pickle.HIGHEST_PROTOCOL))
    for config in configs:
        accounts = []
        for key in sorted(inputs):
            qty, value = (5, 1000) if key[1] == 'TOPIX' else (10, 10)
            signals = decisions(candidate_map[(key, config['count'])][config['family']], config['fraction'],
                                inputs[key]['last'][0], inputs[key]['tick'])
            signal_map[(key, config['id'])] = signals
            a = execute(inputs[key], features[key], signals, qty, value)
            a['intervals'] = export.intervals(inputs[key], a)
            a['candidate_count'] = len(signals)
            accounts.append(a)
            assert a['win_qty'] + a['loss_qty'] + a['flat_qty'] == a['cycles'] * qty
            export.save_csv(HERE / '台帳' / config['id'] / f'{key[0]}_{key[1]}.csv', ledger(a))
            session_rows.append(dict(手法=config['id'], セッション=key[0], 銘柄=key[1], 利益円=a['profit'], 損失円=a['loss'],
                                     収支円=a['net'], 利益枚数=a['win_qty'], 損失枚数=a['loss_qty'], 同値枚数=a['flat_qty'],
                                     枚数差=a['win_qty']-a['loss_qty'], 取引組数=a['cycles'], 初期幅単位損益=a['w_net'],
                                     中値収支円=a['sensitivity']['中値']['net'], 気配収支円=a['sensitivity']['売買気配']['net']))
        summary, weeks, periods = {}, {}, {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [a for a in accounts if a['symbol'] == symbol]
            summary[symbol] = summarize(selected)
            summary[symbol]['sensitivity'] = {mode: export.summarize([dict(a['sensitivity'][mode], session=a['session']) for a in selected])
                                               for mode in ('中値', '売買気配')}
            weeks[symbol] = {w: summarize([a for a in selected if week(a['session']) == w])
                             for w in sorted({week(s) for s in sessions})}
            periods[symbol] = {name: summarize([a for a in selected if a['session'] in keys])
                               for name, keys in [('前10場', sessions[:10]), ('次9場', sessions[10:19]), ('後4場', sessions[19:])]}
            summary[symbol]['period_pass'] = all(v['net'] > 0 for v in periods[symbol].values())
            summary[symbol]['candidate_pass'] = (summary[symbol]['base_pass'] and summary[symbol]['period_pass']
                                                  and all(a['net'] > 0 for a in summary[symbol]['sensitivity'].values()))
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
                                      meta=dict(conditions=12, accounts=12 * len(inputs), qty='TOPIXmini5枚/NK225micro10枚、追加なし、上限10/20枚',
                                                scope='保存済み2026-09-21〜2026-10-06の23場', current_api_requests=0, unseen=False,
                                                main_ids=[m['id'] for m in configs if m['primary']],
                                                common_candidates=[m['id'] for m in output if all(m['summary'][s]['candidate_pass'] for s in ('TOPIX', 'NK225'))])))


if __name__ == '__main__':
    main()
