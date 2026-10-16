"""二市場状態による配分を事前固定し、同じ注文モデルで全30場を再生する。"""

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
    機能: 保存済み仕様又は検算結果を読む。
    引数: path(Path)。
    返り値: object。pickle又はJSONの内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def clean(value: object) -> object:
    """
    機能: 数値計算器の整数・配列を日本語JSONへ保存可能な型へ変換する。
    引数: value(object)。
    返り値: object。組は列、配列は列、NumPy数値はPython数値へ変換。
    """
    if isinstance(value, dict):
        return {str(key): clean(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(child) for child in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    return value


def save(path: Path, value: object) -> None:
    """
    機能: 当作業内だけに再現資料を保存する。
    引数: path(Path)、value(object)。
    返り値: None。他の作業又は読み取り専用原本へは保存しない。
    """
    assert path.resolve().is_relative_to(HERE)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False)+'\n', encoding='utf-8')


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: オフライン検証中の外部通信を禁止する。
    引数: args(tuple)、kwargs(dict、任意の接続指定)。
    返り値: None。常に例外を出す。
    """
    raise RuntimeError('保存された30セッションだけを検証します')


def freeze() -> None:
    """
    機能: 新損益を見る前に条件、主、評価、入力、監査を指紋付きで固定する。
    引数: なし。
    返り値: None。既存の固定内容は上書きしない。
    """
    target = HERE/'事前固定.json'
    assert not target.exists()
    assert not list((HERE/'results').glob('*.json'))
    material = data.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 30
    for symbol in catalog.SYMBOLS:
        assert {p.stem for p in (ROOT/'book'/symbol).glob('*.jsonl')} == set(sessions)
    proofs = list((HERE/'audit').glob('*.json'))
    completed = [p for p in proofs if read(p).get('全合格') is True]
    assert any('人工' in p.name for p in completed), '人工監査が必要です'
    assert any('実観測' in p.name and read(p).get('検査件数', {}).get('未来切断', 0) > 0
               for p in completed), '実入力未来切断が必要です'
    assert any('端点' in p.name for p in completed), '二市場状態素材の独立監査が必要です'
    files = [HERE/name for name in ('catalog.py', 'data.py', 'engine.py',
                                    'strategy.py', 'accounting.py', 'research.py')]
    files += list((HERE/'theory').glob('*.json'))
    files += list((HERE/'audit').glob('*.py')) + proofs
    files += material['paths']
    files += [ROOT/'work/wave_v83/prepared/価格入力の照合.json',
              ROOT/'work/wave_v89/theory/現在の二市場状態で追従と往復を選ぶ案の既往差分と最小入力接続.json']
    save(target, dict(
        条件=catalog.catalog(), 主=catalog.PRIMARY, 全30=sessions,
        前16=sessions[:16], 後14=sessions[16:],
        意味='全30場は既に調査済み。前後比較は既知期間内の再評価で、未見検証ではない。',
        目的='同商品内の手数料後の総利益/(総利益+総損失)80%を両商品で目指す。各日の黒字、平均勝ち/負け、日中清算時価下落は別に評価。無取引は勝ちへ含めない。',
        二つの源='J2の二市場共通進行を追う新規と始値0.4%追尾・最大30分返済。O06はanchor±8ラージ呼値に現在値が到達した側のみ持続指値を予約、約定後1幅損切り/3幅利確。上下二本常設ではない。',
        状態='双方300秒ER>=高閾値かつ旧J2共通方向・許可を満たす時は追従、双方ER<=低閾値かつ現在中値が現在を除く過去180秒範囲内・共通進行なしの時は往復。双方の更新を伴う連続10秒が基本。欠測、総変動0、未充足は不明。',
        配分='固定併用はTOPIX指定枚数、NK225はその2倍の源別固定枠。枠を貸さない。排他的選択は一源だけ予約又は保有しTOPIX10/NK20の共有枠。保有・新規予約を含め片方向上限を厳守。',
        注文='共通rawseqと最終約定時計代理。strict過去grid-1秒特徴を原本へ公開し、成行は判断より後の次有効買ask/売bid。持続指値は予約より後のask<=limit又はbid>=limitで元指値価格に全量約定する代理。5秒追加遅延なし。ミニ/マイクロ板待ち順位と全量約定は未検証。',
        品質='J2新規は原板quality/resetを確認。O06新規は原板現在値/気配正常と、最後のmodeが格子から10秒以内であることを使い、旧源にない原板quality/reset除外は追加しない。次格子まで旧modeが残るため完全に瞬時の二市場分類ではない。',
        取消='入口ゲートのみは旧anchorを保持。取消追加は状態失効を判断した後の次有効気配で既有効指値の約定を先に扱い、未約定の場合のみ取消を有効にする。その後の現在値で次cycleのanchorを再設定。判断以前の損失約定を消さない。',
        取消時計='通常取消code3及びcode6/detail0は取消判断行・時刻を記録する。既知の新規終了時刻によるcode6/detail1は公開rowと各源の固定終了時計で解釈し、そのdecision列に残る元新規予約時計を取消判断時計と混同しない。',
        保有='保有中は元の返済規則を継続。Xだけ往復源に反対の追従状態が成立した時の成行全返済を追加。不明への変化だけで既保有を強制返済しない。',
        境界='セッション末は既知時刻で未約定取消、全保有返済。J2の新規終了はlimit-300秒、O06はlimit-120秒、返済予定は両方limit-60秒。旧J2の場末観測後次quoteと異なり、予定時刻以後最初のquoteへ返済する特例。全条件セッション間の建玉持越しなし。時刻順序の詳細はengineの公開コメントとイベント列を参照。',
        料金='TOPIXminiは片道1枚41.8円・1pt1000円、NK225microは11円・1pt10円。新規/返済1注文ごとの合計を1円未満切捨て。源間で発注を相殺して料金を減らさない。',
        選定='理論主D_Cを結果で差替えない。参考代表は前16で双方20親/8活動場を足切り、双方黒字かつ平均勝ち/負け>1を優先、次に双方黒字、次に活動充足。各段階で悪い側の金額利益割合最大→悪い側の黒字活動場割合最大→利益割合和最大→ID順。全30選択の参考は別表示。',
        対照='J10/O10と、同数量のJ8/O2をM82と比較する。M82の各源は同量単独の注文・曲線に一致するか検査。J10は旧J2の次気配モデルを照合し、O10は旧即時モデルから次気配へ変更した差を明示する。',
        SHA256={str(p.relative_to(ROOT)): data.digest(p) for p in sorted(set(files))},
        API取得=0, 実注文=0, 新損益閲覧前固定=True))
    print('27条件・理論主D_Cを損益前に固定しました', flush=True)


def validate(fixed: dict) -> None:
    """
    機能: 正式な再生前に凍結ファイルとカタログの一致を確認する。
    引数: fixed(dict、事前固定の内容)。
    返り値: None。変更があれば例外を出す。
    """
    assert fixed['条件'] == catalog.catalog()
    for relative, digest in fixed['SHA256'].items():
        assert data.digest(ROOT/relative) == digest, relative


def ledger(output: dict, prepared: dict) -> dict:
    """
    機能: 全原板会計の指紋と疎な状態変化を保存し、元の配列から検算可能にする。
    引数: output(dict、執行結果)、prepared(dict、当該口座の入力)。
    返り値: dict。注文・親・予約イベントと終端状態を含む。
    """
    trace = output['target_trace']
    changed = np.flatnonzero(np.r_[True, np.any(np.diff(trace, axis=0) != 0, axis=1)])
    changed = np.unique(np.r_[changed, len(trace)-1])
    answer = {key: output[key] for key in
              ('orders', 'trades', 'events', 'stats', 'slots', 'order_columns',
               'trade_columns', 'trace_columns', 'event_columns', 'stat_columns',
               'slot_columns', 'reasons', 'event_codes')}
    answer.update(trace_changes=np.column_stack((changed, trace[changed])),
                  curve_SHA256=hashlib.sha256(output['curve'].tobytes()).hexdigest(),
                  source_curve_SHA256=hashlib.sha256(output['source_curve'].tobytes()).hexdigest(),
                  source_curve_column_SHA256=[hashlib.sha256(output['source_curve'][:, i].tobytes()).hexdigest()
                                               for i in range(2)],
                  target_trace_SHA256=hashlib.sha256(trace.tobytes()).hexdigest(),
                  input_rows=len(trace),
                  state_SHA256=hashlib.sha256(prepared['signal']['mode'].tobytes()).hexdigest())
    return answer


def run_one(config: dict, fixed: dict, prepared: dict) -> str:
    """
    機能: 変更不能な条件で60口座を再生し、全30場の親別金額を保存する。
    引数: config/fixed/prepared(dict)。
    返り値: str。完了した条件ID。
    """
    target = HERE/'results'/f"{config['id']}.json"
    assert not target.exists()
    rows, records = [], {}
    for key in sorted(prepared):
        output = strategy.play(config, key, prepared)
        rows.append(accounting.account(key, output))
        records[key] = ledger(output, prepared[key])
    path = HERE/'ledgers'/f"{config['id']}.pkl"
    save(path, records)
    periods = {name: {symbol: accounting.aggregate(rows, symbol, sessions)
                      for symbol in catalog.SYMBOLS}
               for name, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']),
                                      ('後14', fixed['後14']),
                                      ('デイ', [s for s in fixed['全30'] if s.endswith('_Day')]),
                                      ('ナイト', [s for s in fixed['全30'] if s.endswith('_Night')])]}
    save(target, dict(config=config, rows=rows, periods=periods,
                      ledger_SHA256=data.digest(path)))
    return config['id']


def run(workers: int, ids: list[str] | None) -> None:
    """
    機能: 独立条件だけを並列に再生する。
    引数: workers(int、並列数)、ids(list[str] | None、指定ID)。
    返り値: None。未完条件だけを実行する。
    """
    fixed = read(HERE/'事前固定.json')
    validate(fixed)
    material = data.load_inputs()
    configs = [c for c in fixed['条件'] if ids is None or c['id'] in ids]
    if ids is not None:
        assert set(ids) == {c['id'] for c in configs}
    caches = {}
    for c in configs:
        key = (c['high_er'], c['low_er'], c['confirm_seconds'])
        if key not in caches:
            caches[key] = strategy.prepare(material, c)
    # ----------------------------------------
    # 準備は価格と過去特徴だけ。条件間で状態・損益・連敗を渡さない。
    todo = [c for c in configs if not (HERE/'results'/f"{c['id']}.json").exists()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, c, fixed,
                              caches[(c['high_er'], c['low_er'], c['confirm_seconds'])]): c
                   for c in todo}
        for future in as_completed(futures):
            print(f'{future.result()} 全30場完了', flush=True)


def main() -> None:
    """
    機能: 事前固定又は保存原本による再生を起動する。
    引数: CLIのfreeze/run(bool)、workers(int)、ids(list[str] | None)。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description='二市場状態と異なる二手法への配分を調べる')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--ids', nargs='+')
    args = parser.parse_args()
    socket.socket.connect, socket.create_connection = deny, deny
    if args.freeze:
        freeze()
    elif args.run:
        run(args.workers, args.ids)
    else:
        raise SystemExit('事前固定又は再生を指定してください')


if __name__ == '__main__':
    main()
