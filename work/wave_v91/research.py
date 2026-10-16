"""旧30場で条件と参考代表を固定し、追加Dayを後から一度だけ検証する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

import accounting
import catalog
import data
import strategy


def read(path: Path) -> object:
    """
    機能: 保存資料を読み取る。
    引数: path(Path)。
    返り値: object。JSON又はpickleの内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value: object) -> object:
    """
    機能: 数値型と配列を有限JSONに保存できる標準型へ変換する。
    引数: value(object)。
    返り値: object。配列・組・NumPy数値を列と標準数値にする。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(path: Path, value: object) -> None:
    """
    機能: 新作業内だけに再現資料を保存する。
    引数: path(Path)、value(object)。
    返り値: None。保存先を先に作成し、解決済みの両絶対パスを検査する。
    """
    assert path.absolute().is_relative_to(HERE.absolute())
    path.parent.mkdir(parents=True, exist_ok=True)
    assert path.resolve().is_relative_to(HERE.resolve())
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False)+'\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 検証中の外部接続を禁止する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。常に例外を出す。
    """
    raise RuntimeError('保存された31セッションだけを使用します')


def freeze() -> None:
    """
    機能: 38条件の主・素材・評価と追加Dayの事前位置付けを固定する。
    引数: なし。
    返り値: None。完結した新条件損益を見る前に一度だけ保存する。
    """
    assert not (HERE/'事前固定.json').exists()
    assert not list((HERE/'results').glob('*.json'))
    assert not list((HERE/'extra/results').glob('*.json'))
    material = data.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31 and sessions[-1] == '2026-10-12_Day'
    for symbol in catalog.SYMBOLS:
        assert {p.stem for p in (ROOT/'book'/symbol).glob('*.jsonl')} == set(sessions)
    proofs = list((HERE/'audit').glob('*.json'))
    good = [p for p in proofs if read(p).get('全合格') is True]
    assert any('人工' in p.name and read(p).get('条件数') == 38 for p in good)
    assert any('実' in p.name and read(p).get('条件数') == 38 for p in good)
    assert any('対照' in p.name for p in good)
    paths = [HERE/name for name in ('catalog.py', 'engine.py', 'strategy.py', 'data.py',
                                    'research.py', 'accounting.py', 'controls.py')]
    paths += list((HERE/'inputs').glob('*.py'))+list((HERE/'inputs').glob('*.json'))
    paths += list((HERE/'theory').glob('*.json'))
    paths += list((HERE/'audit').glob('*.py'))+proofs+material['paths']
    save(HERE/'事前固定.json', dict(
        条件=catalog.catalog(), 主=catalog.PRIMARY, 全31=sessions, 旧30=sessions[:-1],
        前16=sessions[:16], 後14=sessions[16:-1], 追加1=sessions[-1:],
        意味='旧30は既知期間の再探索。追加10月12日Dayは価格素材準備だけで完結損益未閲覧。主は事前固定し、参考代表を旧前16で固定後に追加Dayを一度検証する。1場だけで一般性能を証明しない。',
        目的='商品ごとの手数料後総利益/(総利益+総損失)80%を目指す。黒字場数・平均勝ち/負け・含み損を含む下落を別評価。無取引は勝ちへ含めない。',
        待機='低ER・範囲内の旧確認で往復仮説を一度準備。持続型は分類mode0又はER不明だけではanchorを変更せず、両current.validと最新格子10秒以内、自p/q正常なら新規可。明確共同方向(又は別対照trend300)とanchor±3W破りで解除。全返済後も解除し次の低ER準備を待つ。',
        取消='解除した未約定指値は取消を予約し、次有効原板で生きた指値成立を優先、成立しなければ取消を有効にする。効力同じ行に再準備しない。指標欠測を既設指値の約定不能と混同しない。',
        入口='元J2パルスは双方300秒価格進行と短期確認・逆OFI除外・弱い側1/4を保持。追加高ER状態ゲートの0秒化と全解除を分け、往復mode時計は変えない。既存確認と追加条件は異なる証拠である。',
        出口='commonは双方300秒各3bp以上＋双方30秒ret同方向。quotesは双方30秒bid/ask各1ラージ呼値反対。ERに依存せず0/10/15秒を確認。eitherはそれぞれ独立時計で確認後OR。新出口は源別に指定し、成立時の返済は次有効気配。既往でJ2利益を削った反例を保持する。',
        利益保護='旧O06はLastPriceで1W損切り・3W利確。trail対照はLastPrice固定損切りを保持し、売bid/買askで1W順行後に最高有利気配から0.5W追尾。最高値更新と同じ観測に遡って新線で約定しない。',
        価格幅='8ラージ呼値と、始値×.05/.10/.15%をラージ呼値へ切上げ最低2呼値で比較。実NK10pt/TOP0.5ptで、同8ticksは同率ではない。倍率の違いを円合計順位へ混ぜない。',
        主の説明='P_G82_HUNL：固定追従8/反発2枠、J2追加ゲート解除、持続準備・始値0.1%幅・利益保護・双方common10秒反対返済。任意の保有期限は外し、保険線・反対証拠・既知場末で返済。源ごとの管理と当時選択を一つの注文状態で実行する。',
        枚数='TOPIXmini片方向10枚、NK225micro20枚。固定配分8/2と16/4は貸出なし、排他全枠10/20は予約又は保有が一源だけ。新規予約を含め上限を守り、源親は相殺せず記録。',
        約定='ラージの原本CurrentPriceTime代理とrawseq順、grid−1秒より厳密に過去の特徴だけ。成行は判断後次有効買ask/売bid、指値は予約後ask<=limit/bid>=limitで当時気配価格。全数量約定・小商品実板・待ち順位は未検証、5秒追加遅延なし。',
        場末='既知limit−60秒の返済。新規終了はJ2limit−300/O06limit−120秒。常にセッション内全返済し、追加Dayもcut後の有効気配で通常清算できる。全保存有効行で清算時価と残玉返済料を評価し、除外・未観測極値は補完しない。',
        料金='片道1枚TOPIXmini41.8円/NK225micro11円、倍率1pt1000円/10円。1注文合計切捨てを両側課金。源間でネット発注しない。',
        選定='旧前16で両商品20親/8活動場以上を足切り、両黒字かつ平均勝負>1優先、次に両黒字、次に活動充足。悪い側金額利益割合最大→悪い側黒字活動場率最大→割合和最大→ID。参考代表をJSON固定し、その後追加Dayを検証。主は結果で差替えない。',
        対照='旧30のJ10/J8/O10/O2/M82/B_QAは旧Qモデルの全注文・親・全行会計に完全一致を要求。新Dayを対照一致の名目で事前に損益閲覧しない。',
        SHA256={str(p.relative_to(ROOT)): data.digest(p) for p in sorted(set(paths))},
        完結新条件損益閲覧前固定=True, API取得=0, 実注文=0))
    print('38条件・主P_G82_HUNLを追加Day損益前に固定しました', flush=True)


def validate(fixed: dict) -> None:
    """
    機能: 再生前に条件と全凍結依存の不変を照合する。
    引数: fixed(dict)。
    返り値: None。不一致なら停止する。
    """
    assert fixed['条件'] == catalog.catalog()
    for path, expected in fixed['SHA256'].items():
        assert data.digest(ROOT/path) == expected, path


def ledger(output: dict, prepared: dict) -> dict:
    """
    機能: 注文・親・イベントと全有効行の指紋を保持する。
    引数: output/prepared(dict)。
    返り値: dict。全行traceは変化行に圧縮し、独立復元可能にする。
    """
    trace = output['target_trace']
    changed = np.unique(np.r_[np.flatnonzero(np.r_[True, np.any(np.diff(trace, axis=0) != 0, axis=1)]), len(trace)-1])
    result = {field: output[field] for field in
              ('orders', 'trades', 'events', 'stats', 'slots', 'order_columns', 'trade_columns',
               'trace_columns', 'event_columns', 'stat_columns', 'slot_columns', 'reasons', 'event_codes')}
    result.update(trace_changes=np.column_stack((changed, trace[changed])), input_rows=len(trace),
                  curve_SHA256=hashlib.sha256(output['curve'].tobytes()).hexdigest(),
                  source_curve_SHA256=hashlib.sha256(output['source_curve'].tobytes()).hexdigest(),
                  target_trace_SHA256=hashlib.sha256(trace.tobytes()).hexdigest(),
                  source_curve_column_SHA256=[hashlib.sha256(output['source_curve'][:, i].tobytes()).hexdigest()
                                              for i in range(2)])
    return result


def run_one(config: dict, sessions: list[str], base: Path, prepared: dict) -> str:
    """
    機能: 指定した期間だけを順次再生し、旧期間と追加Dayを混ぜず保存する。
    引数: config(dict)、sessions(list[str])、base(Path)、prepared(dict)。
    返り値: str。完了条件ID。
    """
    target = base/'results'/f"{config['id']}.json"
    assert not target.exists()
    rows, records = [], {}
    for key in sorted(k for k in prepared if k[0] in sessions):
        output = strategy.play(config, key, prepared)
        rows.append(accounting.account(key, output))
        records[key] = ledger(output, prepared[key])
    path = base/'ledgers'/f"{config['id']}.pkl"
    save(path, records)
    name = '追加1' if len(sessions) == 1 else '旧30'
    periods = {name: {s: accounting.aggregate(rows, s, sessions) for s in catalog.SYMBOLS}}
    if len(sessions) == 30:
        for label, subset in [('前16', sessions[:16]), ('後14', sessions[16:])]:
            periods[label] = {s: accounting.aggregate(rows, s, subset) for s in catalog.SYMBOLS}
    save(target, dict(config=config, rows=rows, periods=periods, ledger_SHA256=data.digest(path)))
    return config['id']


def score(result: dict) -> tuple:
    """
    機能: 旧前16だけで、悪い側の利益割合と黒字率を優先する。
    引数: result(dict)。
    返り値: tuple。昇順の固定採点。
    """
    rows = [result['periods']['前16'][s] for s in catalog.SYMBOLS]
    shares = [r['profit_share'] if r['profit_share'] is not None else -1 for r in rows]
    rates = [r['positive_session_rate'] if r['positive_session_rate'] is not None else -1 for r in rows]
    return -min(shares), -min(rates), -sum(shares), result['config']['id']


def select() -> None:
    """
    機能: 全38の旧30再生後、新Dayの完結損益前に参考代表を固定する。
    引数: なし。
    返り値: None。追加結果がある場合又は選定済みの場合は再選定しない。
    """
    assert not (HERE/'前16参考代表.json').exists()
    assert not list((HERE/'extra/results').glob('*.json'))
    fixed = read(HERE/'事前固定.json')
    validate(fixed)
    results = [read(HERE/'results'/f"{c['id']}.json") for c in fixed['条件']]
    active = [r for r in results if all(r['periods']['前16'][s]['campaigns'] >= 20
                                      and r['periods']['前16'][s]['active_sessions'] >= 8 for s in catalog.SYMBOLS)]
    positive = [r for r in active if all(r['periods']['前16'][s]['net'] > 0 for s in catalog.SYMBOLS)]
    good = [r for r in positive if all(r['periods']['前16'][s]['payoff'] is not None
                                      and r['periods']['前16'][s]['payoff'] > 1 for s in catalog.SYMBOLS)]
    pool = good or positive or active or results
    chosen = min(pool, key=score)['config']['id']
    save(HERE/'前16参考代表.json', dict(全合格=True, selected=chosen, primary=catalog.PRIMARY,
         level=0 if good else 1 if positive else 2 if active else 3,
         eligible=[r['config']['id'] for r in pool], scores={r['config']['id']: score(r) for r in pool},
         追加Day完結損益前選定=True, 旧30既知=True,
         固定SHA256=data.digest(HERE/'事前固定.json'),
         結果SHA256={str((HERE/'results'/f"{c['id']}.json").relative_to(ROOT)):
                    data.digest(HERE/'results'/f"{c['id']}.json") for c in fixed['条件']}))
    print(f'追加Dayの結果前に参考代表 {chosen} を固定しました', flush=True)


def run(workers: int, extra: bool) -> None:
    """
    機能: 旧30と追加1を別手順で再生し、追加結果による再選定を防ぐ。
    引数: workers(int)、extra(bool、追加DayだけならTrue)。
    返り値: None。既に完了した条件を繰り返さない。
    """
    fixed = read(HERE/'事前固定.json')
    validate(fixed)
    if extra:
        selection = read(HERE/'前16参考代表.json')
        assert selection['追加Day完結損益前選定'] and selection['固定SHA256'] == data.digest(HERE/'事前固定.json')
        for relative, expected in selection['結果SHA256'].items():
            assert data.digest(ROOT/relative) == expected
    base, sessions = (HERE/'extra', fixed['追加1']) if extra else (HERE, fixed['旧30'])
    for directory in ('results', 'ledgers'):
        (base/directory).mkdir(parents=True, exist_ok=True)
    material = data.load_inputs()
    caches = {}
    configs = [c for c in fixed['条件'] if not (base/'results'/f"{c['id']}.json").exists()]
    for c in configs:
        key = tuple(c.get(name) for name in ('high_er', 'low_er', 'confirm_seconds', 'trend_mode_confirm_seconds',
                     'range_width_mode', 'range_width_fraction', 'width_ticks', 'reverse_kind', 'reverse_confirm_seconds'))
        if key not in caches:
            caches[key] = strategy.prepare(material, c)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, c, sessions, base,
                              caches[tuple(c.get(name) for name in ('high_er', 'low_er', 'confirm_seconds',
                                  'trend_mode_confirm_seconds', 'range_width_mode', 'range_width_fraction',
                                  'width_ticks', 'reverse_kind', 'reverse_confirm_seconds'))]) for c in configs]
        for future in as_completed(futures):
            print(f'{future.result()} {"追加1" if extra else "旧30"}完了', flush=True)


def main() -> None:
    """
    機能: 条件凍結→旧期間→参考選定→追加確認を明示したCLIを実行する。
    引数: CLIのfreeze/run_old/select/run_extra(bool)、workers(int)。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description='基準保持と反対返済を追加Day前に固定する')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run-old', action='store_true')
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--run-extra', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    socket.socket.connect, socket.create_connection = deny, deny
    if args.freeze:
        freeze()
    elif args.run_old:
        run(args.workers, False)
    elif args.select:
        select()
    elif args.run_extra:
        run(args.workers, True)
    else:
        raise SystemExit('凍結・旧再生・選定・追加確認を順に指定してください')


if __name__ == '__main__':
    main()
