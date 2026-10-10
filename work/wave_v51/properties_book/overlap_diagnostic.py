"""既存観測点のOFIと価格応答の重複を調べる。閾値・観測点・売買規則は変更しない。"""
from pathlib import Path
import gzip
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    """機能: 分散がある組だけのPearson相関を返す。

    引数: x/y(ndarray)。返り値: float|None は相関。
    """
    if len(x) < 4 or x.std() < 1e-12 or y.std() < 1e-12:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def partial(x: np.ndarray, y: np.ndarray, controls: np.ndarray) -> float | None:
    """機能: 固定した現在説明変数との線形重複を除いた記述的な相関を求める。

    引数: x/y/controls(ndarray)。返り値: float|None は残差同士の相関。
    回帰係数を売買へ利用せず、予測モデルの選抜も行わない。
    """
    if len(x) < 6:
        return None
    matrix = np.column_stack([np.ones(len(x)), controls])
    rx = x - matrix @ np.linalg.lstsq(matrix, x, rcond=None)[0]
    ry = y - matrix @ np.linalg.lstsq(matrix, y, rcond=None)[0]
    return correlation(rx, ry)


def ranked_correlation(x: np.ndarray, y: np.ndarray) -> float | None:
    """機能: 同順位を平均順位で扱うSpearman相関を返す。

    引数: x/y(ndarray)。返り値: float|None は順位相関。
    """
    return correlation(pd.Series(x).rank().to_numpy(), pd.Series(y).rank().to_numpy())


def main() -> None:
    """機能: 同じ観測点の同期説明・価格調整後相関・相手OFIを全期間区分で比較する。

    引数: なし。返り値: なし(None)。追加診断の定義は計算前に保存する。
    """
    definition = dict(区分='一次集計を閲覧した後の記述診断。真正未見ではない。',
                      不変='観測間隔・品質条件・圧力閾値・期間区分を変更しない。追加の売買・閾値最適化なし。',
                      自市場='OFI/近接数量変化/近接厚さと直近価格反応の相関、将来変化との相関から直近価格反応との線形重複を除いた偏相関。',
                      相手市場='相手の連続OFIと将来自市場変化の相関。自市場OFIと直近価格反応を同時調整した偏相関。相手遅延は元の60/0秒のまま。',
                      注意='全期間の記述的回帰であり将来予測器を学習/評価したものではない。非線形追加価値や因果を証明しない。')
    path = HERE / '追加診断固定.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf8')) == definition
    else:
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding='utf8')
    rows = json.loads(gzip.decompress((HERE / '観測点.json.gz').read_bytes()))
    groups = json.loads((HERE / '市場性質結果.json').read_text(encoding='utf8'))['期間']
    own, peer = [], []
    for period, sessions in groups.items():
        for symbol in ('TOPIX', 'NK225'):
            chosen = [r for r in rows if r['session'] in sessions and r['symbol'] == symbol]
            for feature in ('ofi', 'near', 'pressure'):
                values = np.array([r['state'][feature] for r in chosen])
                response = np.array([r['state']['response'] for r in chosen])
                future = {}
                for h in ('60', '300', '900'):
                    valid = [r for r in chosen if r['future'][h] is not None]
                    x = np.array([r['state'][feature] for r in valid])
                    y = np.array([r['future'][h] for r in valid])
                    z = np.array([r['state']['response'] for r in valid])
                    future[h] = dict(n=len(valid), raw=correlation(x, y), adjusted_price=partial(x, y, z),
                                     spearman=ranked_correlation(x, y), price_response_pearson=correlation(z, y),
                                     price_response_spearman=ranked_correlation(z, y))
                own.append(dict(period=period, symbol=symbol, feature=feature, n=len(chosen),
                                same_window=correlation(values, response), future=future))
            for delay in ('60', '0'):
                future = {}
                for h in ('60', '300', '900'):
                    valid = [r for r in chosen if r['future'][h] is not None and 'ofi' in r['peer'][delay]]
                    x = np.array([r['peer'][delay]['ofi'] for r in valid])
                    y = np.array([r['future'][h] for r in valid])
                    z = np.array([[r['state']['response'], r['state']['ofi']] for r in valid])
                    future[h] = dict(n=len(valid), raw=correlation(x, y), adjusted_own=partial(x, y, z),
                                     spearman=ranked_correlation(x, y), price_response_pearson=correlation(z[:, 0], y),
                                     price_response_spearman=ranked_correlation(z[:, 0], y))
                peer.append(dict(period=period, symbol=symbol, delay=int(delay), future=future))
    (HERE / '価格応答との重複.json').write_text(json.dumps(dict(自市場=own, 相手市場=peer), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps([r for r in own if r['period'] == '全23'], ensure_ascii=False))


if __name__ == '__main__':
    main()
