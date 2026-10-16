"""旧27条件を保持し、古い指値と価格改善の15条件を追加固定して再生する。"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(WORK))
import research as BASE


def module(name: str, path: Path) -> object:
    """
    機能: 新旧の同名モジュールを衝突させず取り込む。
    引数: name(str)、path(Path)。
    返り値: object。固有名で登録したモジュール。
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


CATALOG = module('追加二軸条件90r2', HERE/'catalog.py')
STRATEGY = module('追加二軸接続90r2', HERE/'strategy.py')


def freeze() -> None:
    """
    機能: 修正前の大損失を受け、価格改善と基準更新を新損益前に固定する。
    引数: なし。
    返り値: None。旧固定を変更しない。新固定は上書きしない。
    """
    assert not (HERE/'事前固定.json').exists()
    assert not list((HERE/'results').glob('*.json'))
    old = BASE.read(WORK/'事前固定.json')
    BASE.validate(old)
    proofs = list((HERE/'audit').glob('*.json'))
    done = [p for p in proofs if BASE.read(p).get('全合格') is True]
    assert any('人工' in p.name for p in done)
    assert any('実' in p.name and BASE.read(p).get('検査件数', {}).get('未来切断', 0) > 0 for p in done)
    paths = [HERE/name for name in ('catalog.py', 'engine.py', 'strategy.py', 'research.py')]
    paths += list((HERE/'theory').glob('*.json'))
    paths += list((HERE/'audit').glob('*.py'))+proofs
    paths += [WORK/'事前固定.json',
              WORK/'audit/全27条件の旧指値価格と当時気配差及びER実尺度の独立診断.json']
    hashes = dict(old['SHA256'])
    hashes.update({str(p.relative_to(ROOT)): BASE.data.digest(p) for p in paths})
    BASE.save(HERE/'事前固定.json', dict(
        条件=CATALOG.catalog(), 主=CATALOG.PRIMARY, 全30=old['全30'], 前16=old['前16'], 後14=old['後14'],
        意味=old['意味'], 旧27保持=True, 新損益閲覧前固定=True,
        Q='予約より後の有効気配で指値が成立した場合、その買ask/売bid価格に全量約定。指値を超える不利な価格では約定しない。価格改善を得た実約定価格をIFDの基準にする。板待ち順位・小商品実板・全数量の約定は未確認。',
        A='選択を行う往復源が、空枠かつ有効な往復状態・新規可能へ変わった時だけ、当時CurrentPriceでanchorを更新。未約定/保有中は更新しない。取消効力行は更新せず、その次行以降。既存の全返済時更新と同じ観測で二重cycleを作らない。',
        対照='QのみとAのみを主D_Cと固定枠G82_Cで比較し、両方QAを追加。QのJ10/J8/O10/O2/M82を同一約定モデル対照にする。旧27は価格改善なしの悲観仮定の対照として残す。',
        保持='旧の数量、状態分類、15/30/300秒の過去入力、確認時間、返済線/損切り/利確、予約取消優先、終了時刻、料金は全て保持。5秒追加遅延なし。',
        選定='参考代表はQ=Trueの13条件だけを対象に、旧と同じ前16の足切りと金額採点で選ぶ。Aのみの悲観価格対照を推奨順位へ混ぜない。理論主D_C_QAは差替えない。',
        限界='全30既知。約定仮定の修正による利益増を方向予測能力の向上と呼ばない。旧価格から気配へ差額を足すだけではなく、IFDと後続新規を全て再生する。',
        SHA256=hashes, API取得=0, 実注文=0))
    print('指値価格改善・往復開始基準の追加15条件を新損益前に固定しました', flush=True)


def validate(fixed: dict) -> None:
    """
    機能: 第一段と追加段の固定コード・素材指紋を照合する。
    引数: fixed(dict)。
    返り値: None。不一致なら再生しない。
    """
    assert fixed['条件'] == CATALOG.catalog()
    for path, expected in fixed['SHA256'].items():
        assert BASE.data.digest(ROOT/path) == expected, path


def run_one(config: dict, fixed: dict, prepared: dict) -> str:
    """
    機能: 改善された新規価格と基準に従い、後続判断も全て再生する。
    引数: config/fixed/prepared(dict)。
    返り値: str。完了条件ID。
    """
    target = HERE/'results'/f"{config['id']}.json"
    assert not target.exists()
    rows, ledgers = [], {}
    for key in sorted(prepared):
        output = STRATEGY.play(config, key, prepared)
        rows.append(BASE.accounting.account(key, output))
        ledgers[key] = BASE.ledger(output, prepared[key])
    path = HERE/'ledgers'/f"{config['id']}.pkl"
    BASE.save(path, ledgers)
    periods = {label: {symbol: BASE.accounting.aggregate(rows, symbol, sessions)
                       for symbol in CATALOG.SYMBOLS}
               for label, sessions in [('全30', fixed['全30']), ('前16', fixed['前16']),
                                        ('後14', fixed['後14']),
                                        ('デイ', [s for s in fixed['全30'] if s.endswith('_Day')]),
                                        ('ナイト', [s for s in fixed['全30'] if s.endswith('_Night')])]}
    BASE.save(target, dict(config=config, rows=rows, periods=periods,
                           ledger_SHA256=BASE.data.digest(path)))
    return config['id']


def run(workers: int) -> None:
    """
    機能: 追加15条件の独立口座だけを並列に再生する。
    引数: workers(int)。
    返り値: None。既存完了結果は再計算しない。
    """
    fixed = BASE.read(HERE/'事前固定.json')
    validate(fixed)
    material = BASE.data.load_inputs()
    prepared = STRATEGY.prepare(material, fixed['条件'][0])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, c, fixed, prepared) for c in fixed['条件']
                   if not (HERE/'results'/f"{c['id']}.json").exists()]
        for future in as_completed(futures):
            print(f'{future.result()} 全30場完了', flush=True)


def main() -> None:
    """
    機能: 追加段の事前固定又は保存原本再生を起動する。
    引数: CLIのfreeze/run(bool)、workers(int)。
    返り値: None。
    """
    parser = argparse.ArgumentParser(description='古い指値と価格改善を分けて検証する')
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    BASE.socket.socket.connect, BASE.socket.create_connection = BASE.deny, BASE.deny
    if args.freeze:
        freeze()
    elif args.run:
        run(args.workers)
    else:
        raise SystemExit('事前固定又は再生を指定してください')


if __name__ == '__main__':
    main()
