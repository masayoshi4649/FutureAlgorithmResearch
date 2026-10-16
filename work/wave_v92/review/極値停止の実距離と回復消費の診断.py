"""確認中に消費した回復幅と実取得価格からの極値停止距離を全親で診断する。"""

import importlib.util
from pathlib import Path
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: 保存会計と読取素材を固有名で接続する。
    引数: name(str)、path(Path)。
    返り値: object。読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


REVIEW = module('停止距離独立会計92', HERE/'全場親会計と入口再参加の経路分解.py')
CASES = module('停止距離時刻診断92', HERE/'赤字上位場の中心と回復及び原板診断.py')


def metrics(values: list[dict]) -> dict:
    """
    機能: 事後診断群の取引数・損益と距離分布を求める。
    引数: values(list[dict])。
    返り値: dict。新しい採否条件として実行した成績ではない。
    """
    distances = np.array([v['停止距離_幅'] for v in values])
    recovery = np.array([v['判断時mid回復_幅'] for v in values])
    return dict(親=len(values), 純収支円=sum(v['純収支円'] for v in values),
        利益親=sum(v['純収支円'] > 1e-5 for v in values),
        損失親=sum(v['純収支円'] < -1e-5 for v in values),
        停止距離中央値_幅=float(np.median(distances)) if len(values) else None,
        停止距離90パーセント点_幅=float(np.quantile(distances, .9)) if len(values) else None,
        判断時mid回復中央値_幅=float(np.median(recovery)) if len(values) else None)


def main() -> None:
    """
    機能: 主全209親の失敗線距離・回復消費と固定停止同一新規を照合する。
    引数: なし。
    返り値: None。追加の売買・条件選定や既存成果変更はしない。
    """
    fixed = REVIEW.read(WORK/'事前固定.json')
    for relative, expected in fixed['SHA256'].items():
        assert REVIEW.digest(ROOT/relative) == expected, relative
    primary = fixed['主']
    assert primary == 'R_B25_C_ESTOP'
    config = next(c for c in fixed['条件'] if c['id'] == primary)
    data = module('停止距離保存素材92', WORK/'data.py')
    material = data.load_inputs()
    ledgers, baseline, hashes = {}, {}, {}
    for stage in ('front', 'back'):
        for ident, output in [(primary, ledgers), ('R_B25_C', baseline)]:
            path = WORK/stage/'ledgers'/f'{ident}.pkl'
            accounts = REVIEW.read(path)
            assert not set(accounts) & set(output)
            output.update(accounts)
            hashes[str(path.relative_to(ROOT))] = REVIEW.digest(path)
    summaries, all_rows = {}, {}
    for symbol in ('TOPIX', 'NK225'):
        rows = []
        for key in sorted(ledgers):
            if key[1] != symbol:
                continue
            record = material['prices'][key]
            lookup = REVIEW.parents(baseline[key])
            for trade in ledgers[key]['trades']:
                if int(trade[1]) != 1:
                    continue
                side, decision = int(trade[4]), int(trade[15])
                state = CASES.state_at(ledgers[key], decision)
                width = state['width']
                extreme = state['own_low'] if side == 1 else state['own_high']
                own_row = int(state['own_low_row'] if side == 1 else state['own_high_row'])
                assert abs((record['bid'][own_row]+record['ask'][own_row])/2-extreme) < 1e-8
                own_mid = (record['bid'][decision]+record['ask'][decision])/2
                new_key = (decision, int(trade[2]), 1, side, int(trade[5]), float(trade[6]))
                old = lookup.get(new_key)
                distance = side*(trade[6]-state['witness_stop'])
                rows.append(dict(場=key[0], 親=int(trade[0]),
                    新規判断時刻=CASES.clock(record['time_s'][decision]),
                    方向='買い' if side == 1 else '売り', 純収支円=float(trade[11]),
                    幅=width, 観測極値=float(extreme), 失敗線=state['witness_stop'],
                    実取得価格=float(trade[6]), 停止距離pt=float(distance),
                    停止距離_幅=float(distance/width),
                    判断時mid回復pt=float(side*(own_mid-extreme)),
                    判断時mid回復_幅=float(side*(own_mid-extreme)/width),
                    新規判断spreadpt=float(record['ask'][decision]-record['bid'][decision]),
                    同一新規固定停止収支円=float(old[11]) if old is not None else None,
                    同一新規固定停止との差円=float(trade[11]-old[11]) if old is not None else None))
        all_rows[symbol] = rows
        wide = [r for r in rows if r['停止距離_幅'] > 1+1e-8]
        excess = [r for r in rows if r['判断時mid回復_幅'] > config['recovery_fraction']+1e-8]
        summaries[symbol] = dict(全親=metrics(rows), 固定1幅より広い失敗線=metrics(wide),
            指定回復量を超過した判断=metrics(excess),
            失敗線が広い上位3=sorted(rows, key=lambda r: r['停止距離_幅'], reverse=True)[:3])
    REVIEW.save('主全親の極値停止距離と判断までの回復消費.json', dict(
        全合格=True, 主=primary, 全31既知=True, 商品別=summaries, 全親=all_rows,
        原理='極値外停止は入った価格からの最大損失幅を固定する規則ではない。双方確認が遅いほど自己の回復を消費し、実取得価格から過去極値まで遠くなる。',
        注意=[
            '幅超過群や上位親は事後診断。そこだけ除いて新成績を作らない。',
            '構造停止の改善額と新再参加損益は別。固定1幅より広い予定距離に分類しても、その線で約定する保証はない。',
            '検証していないmin(固定幅,極値停止)や最大回復量制限の収支を本結果から計算しない。'],
        固定SHA256=REVIEW.digest(WORK/'事前固定.json'), SHA256=hashes,
        計算コードSHA256=REVIEW.digest(Path(__file__)), API取得=0, 実注文=0))
    print('主全親の極値距離と確認待ち回復消費を診断しました', flush=True)


if __name__ == '__main__':
    main()
