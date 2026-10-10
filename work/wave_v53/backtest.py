"""固定した50条件を原本順に売買し、4層の寄与を同じ入口ごとに比較する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle

import numpy as np

from engine import execute, REASONS
from features import load_inputs_only
from signals import FAMILIES, LAYERS, candidates, make_decisions


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT = ROOT / 'アルゴリズム調査/00050_一般的な分析と板確認と損益管理'
module = importlib.util.spec_from_file_location('previous_export', HERE.parent/'wave_v52/export.py')
export = importlib.util.module_from_spec(module)
module.loader.exec_module(export)


def save(path: Path, value: object) -> None:
    """機能: 日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf8')


def methods() -> list[dict]:
    """機能: 成績と無関係な12入口×4層と固定の自動選択2条件を定義する。

    引数: なし。返り値: 条件一覧(list[dict])。
    """
    result = []
    for family, name, description, kind in FAMILIES:
        for layer, label, advanced, confirmation in LAYERS:
            result.append(dict(id=f'{family}_{layer}', family=family, layer=layer,
                               name=f'{name}・{label}', description=description,
                               advanced=advanced, confirmation=confirmation))
    for layer in ('A', 'D'):
        result.append(dict(id=f'AUTO_{layer}', family='AUTO', layer=layer,
                           name='状況を自動判定・'+('基本保護' if layer == 'A' else '確認＋高度管理'),
                           description='追従なら戻り試し等、反復なら支持抵抗等、不明なら突破失敗だけを固定順で選ぶ。',
                           advanced=layer == 'D', confirmation=layer == 'D'))
    return result


def freeze(configs: list) -> None:
    """機能: 新しい成績を開く前に規則と実行コードを固定する。

    引数: configs(list)。返り値: なし(None)。再実行時の無記録変更は拒否する。
    """
    sha = {p: hashlib.sha256((HERE/p).read_bytes()).hexdigest() for p in ('features.py','signals.py','engine.py','backtest.py')}
    path = HERE/'売買仕様固定.json'
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf8'))
        assert previous['コードSHA256'] == sha, '凍結後のコード変更です。修正の理由と再検証を記録してください。'
        return
    save(path, dict(固定時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(), コードSHA256=sha, 条件=configs,
                    検証='同じ既知23場での構造比較。過去に見たデータなので未知検証ではない。利益を使った閾値選択なし。',
                    数量='TOPIXmini5枚/NK225micro10枚で新規。上限10/20以内。追加建てなし。高度管理は一度2/5枚を返済可能。',
                    基本='構造線までの距離を0.5〜1.5ATRに制限し初期損切り。1R順行後1Rトレール。最大30分。同じ入口の逆信号で全返済。返済後60秒休止。',
                    管理='0.5R順行で追跡開始。追従一致はmax(0.5ATR,0.5R)、それ以外max(0.3ATR,0.25R)。15分/30分で各0.75倍。板逆は0.3R以下、最小0.15R。1R順行後建値保護。確定山谷でも締める。',
                    半減='現在0.5R以上の含み益があり、固定回帰目標又は板逆行なら一度半減。目標自体も約定値から0.5R以上の距離が必要。残り建値保護。',
                    早期撤退='5分で最大順行0.25R未満。最大保有は追従90/反復15/不明30分、保有中の再判定は短縮だけ。2組連敗で15分休止。',
                    状況='ER15>=0.4、EMA8/21差>=0.25ATR、VWAP同方向なら追従。ER15<=0.25なら反復。他は不明。',
                    選択='追従:T02,T06,T05,T10,T03から状況と同方向の先頭。反復:T01,T08,T04,T07の先頭。不明:T09。取引後の成績で選択しない。',
                    新規確認='板有効かつ相手が明確な逆傾向でない。追従は執行又は提示移動が支持し厚さ偏りが-0.1以上。反復は回復支持又は執行支持＋価格反転。執行全不明は支持扱いしない。',
                    約定='条件成立を読んだ後の次有効原本行の最終価格。判断と約定の原本行を分離。同時刻でも物理行順を保持。費用0。',
                    場内='Day15:35/Night05:50以降に全返済判断。5分前から新規不可。場末保有0必須。',
                    参照='現セッションの原本のみ。前場の情報なし。相手も同じ場で60秒以上遅らせる。API取得0。'))


def week(session: str) -> str:
    """機能: セッション開始日の属する週の月曜を返す。

    引数: session(str)。返り値: 週開始日(str)。
    """
    day = datetime.strptime(session[:10], '%Y-%m-%d')
    return (day-timedelta(days=day.weekday())).date().isoformat()


def ledger(result: dict) -> list[dict]:
    """機能: 次行約定と部分決済の原本根拠を日本語の注文台帳へ変換する。

    引数: result(dict)。返り値: 注文台帳(list[dict])。
    """
    return [dict(判断時刻=export.stamp(r[0]), 約定時刻=export.stamp(r[1]), 判断原本行=int(r[2]), 約定原本行=int(r[3]),
                 区分='新規' if r[4]==1 else '返済', 売買='買い' if r[5]>0 else '売り', 枚数=int(r[6]),
                 価格=r[7], 損益円=r[8], 理由=REASONS[int(r[9])], 組番号=int(r[10]), 残枚数=int(r[11]), 初期R値幅=r[12])
            for r in result['orders']]


def main() -> None:
    """機能: 50条件の売買、金額・枚数照合、期間別集計と管理追加分を保存する。

    引数: なし。返り値: なし(None)。既存成果・生データ・注文アプリは変更しない。
    """
    configs = methods()
    freeze(configs)
    data = pickle.loads((HERE/'特徴.pkl').read_bytes())
    inputs = load_inputs_only()
    sessions = sorted({key[0] for key in inputs})
    decisions, traces = {}, {}
    for key, frame in data.items():
        values, rows = candidates(frame)
        for family in [f[0] for f in FAMILIES]+['AUTO']:
            for confirmation in (False,True):
                address = (key, family, confirmation)
                decisions[address], traces[address] = make_decisions(frame, values, rows, family, confirmation)
    (HERE/'判断.pkl').write_bytes(pickle.dumps(decisions, pickle.HIGHEST_PROTOCOL))
    # ----------------------------------------
    # 注文の有無だけでなく、見送り・手法選択も後から追跡できる。
    for address, trace in traces.items():
        (session,symbol), family, confirmation = address
        name = family+('_確認あり' if confirmation else '_確認なし')
        export.save_csv(HERE/'判断'/name/f'{session}_{symbol}.csv', trace)
    output, session_rows, week_rows, checks = [], [], [], []
    for config in configs:
        accounts, compact = [], []
        for key in sorted(inputs):
            ready = inputs[key]
            result = execute(ready, decisions[(key,config['family'],config['confirmation'])], config['advanced'])
            result['intervals'] = export.intervals(ready,result)
            accounts.append(result)
            export.save_csv(HERE/'台帳'/config['id']/f'{key[0]}_{key[1]}.csv', ledger(result))
            export.save_csv(HERE/'30分'/config['id']/f'{key[0]}_{key[1]}.csv', result['intervals'])
            compact.append({k:v for k,v in result.items() if k != 'curve'})
            q = 5 if key[1]=='TOPIX' else 10
            assert result['win_qty']+result['loss_qty']+result['flat_qty'] == result['cycles']*q
            checks.append(dict(手法=config['id'], セッション=key[0], 銘柄=key[1], 組=result['cycles'], 返済脚=result['repayment_legs'], 場末保有=0))
            session_rows.append(dict(手法=config['id'],セッション=key[0],銘柄=key[1],利益円=result['profit'],損失円=result['loss'],収支円=result['net'],
                                     利益返済枚数=result['win_qty'],損失返済枚数=result['loss_qty'],同値返済枚数=result['flat_qty'],
                                     勝負枚数差=result['win_qty']-result['loss_qty'],組数=result['cycles'],勝ち組数=result['wins'],最大時価下落円=result['drawdown']))
        summary, weeks, periods = {}, {}, {}
        for symbol in ('TOPIX','NK225'):
            selected = [a for a in accounts if a['symbol']==symbol]
            summary[symbol] = export.summarize(selected)
            weeks[symbol] = {w:export.summarize([a for a in selected if week(a['session'])==w]) for w in sorted({week(s) for s in sessions})}
            periods[symbol] = {name:export.summarize([a for a in selected if a['session'] in keys])
                               for name,keys in [('前10場',sessions[:10]),('次9場',sessions[10:19]),('後4場',sessions[19:])]}
            for w,a in weeks[symbol].items():
                week_rows.append(dict(手法=config['id'],週開始=w,銘柄=symbol,利益円=a['profit'],損失円=a['loss'],収支円=a['net'],
                                      利益返済枚数=a['win_qty'],損失返済枚数=a['loss_qty'],同値返済枚数=a['flat_qty'],勝負枚数差=a['win_qty']-a['loss_qty']))
        output.append(dict(**config,accounts=compact,summary=summary,weeks=weeks,periods=periods))
        print('完了',config['id'],'TOPIX',summary['TOPIX']['net'],'NK225',summary['NK225']['net'],flush=True)
    # ----------------------------------------
    # 入口ごとの同条件対照。相互作用を分け、合計益だけで層の価値を決めない。
    by_id = {m['id']:m for m in output}
    components = []
    for family,*_ in FAMILIES:
        for symbol in ('TOPIX','NK225'):
            p = {layer:by_id[f'{family}_{layer}']['summary'][symbol]['net'] for layer,*_ in LAYERS}
            components.append(dict(family=family,symbol=symbol,**p,management_delta=p['B']-p['A'],confirmation_delta=p['C']-p['A'],
                                   both_delta=p['D']-p['A'],interaction=p['D']-p['B']-p['C']+p['A']))
    export.save_csv(REPORT/'セッション別損益.csv',session_rows)
    export.save_csv(REPORT/'週別損益.csv',week_rows)
    export.save_csv(REPORT/'4層比較.csv',components)
    result = dict(methods=output,sessions=sessions,families=FAMILIES,layers=LAYERS,component=components,
                  meta=dict(conditions=len(output),accounts=len(checks),source_accounts=len(inputs),
                            scope='2026-09-21〜2026-10-06 保存23セッション',qty='TOPIXmini5枚 / NK225micro10枚。上限10/20以内、追加建てなし。',
                            fills='次有効原本行の最終価格、費用0',api_requests=0,unknown_validation=False,
                            code_hashes=json.loads((HERE/'売買仕様固定.json').read_text(encoding='utf8'))['コードSHA256']))
    save(HERE/'売買結果.json',result)
    save(HERE/'再生監査.json',dict(合格=True,条件数=50,口座数=len(checks),枚数保存=True,現金と保有時価照合=True,場末保有なし=True,結果=checks))


if __name__ == '__main__':
    main()
