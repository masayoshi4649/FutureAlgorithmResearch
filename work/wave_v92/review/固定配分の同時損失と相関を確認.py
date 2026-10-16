"""配分の安定化効果と、追加戦略自体の収益性を分けて確認する。"""

import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def sha(path: Path) -> str:
    """
    機能: 集計対象の保存資料を内容で識別する。
    引数: path(Path)。対象ファイル。
    返り値: str。SHA256の16進文字列。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 固定された二つの配分の全31場を源別に分解し、同時損失を診断する。
    引数: なし。
    返り値: None。新しい売買、配分探索、損益計算は行わない。
    """
    account_path = WORK / 'analysis/比較結果.json'
    data = json.loads(account_path.read_text(encoding='utf-8'))
    assert data['全合格'] and data['全31既知']
    rows_out = []
    for ident in ('M_RB25_C', 'M_KS25'):
        for symbol in ('TOPIX', 'NK225'):
            rows = [row for row in data['results'][ident]['rows'] if row['symbol'] == symbol]
            assert len(rows) == 31
            trend = np.array([row['sources']['J2']['net'] for row in rows], dtype=float)
            rebound = np.array([row['sources']['O06']['net'] for row in rows], dtype=float)
            combined = np.array([row['net'] for row in rows], dtype=float)
            assert np.array_equal(trend + rebound, combined)
            trend_control = {row['session']: row for row in data['results']['J10']['rows']
                             if row['symbol'] == symbol}
            source_control = {row['session']: row for row in data['results']['J8']['rows']
                              if row['symbol'] == symbol}
            assert np.array_equal(trend, [source_control[row['session']]['net'] for row in rows])
            control = np.array([trend_control[row['session']]['net'] for row in rows], dtype=float)
            total = data['results'][ident]['periods']['全31'][symbol]
            assert total['net'] == combined.sum()
            sources = total['sources']
            numerator = sum(value['profit'] for value in sources.values())
            denominator = sum(value['profit'] + value['loss'] for value in sources.values())
            assert numerator == total['profit'] and denominator == total['profit'] + total['loss']
            assert abs(numerator / denominator - total['profit_share']) < 1e-12
            simultaneous_active = np.array([row['sources']['J2']['campaigns'] > 0 and
                                            row['sources']['O06']['campaigns'] > 0 for row in rows])
            rows_out.append(dict(
                手法=ident, 銘柄=symbol, 場数=31, 総利益=total['profit'], 総損失=total['loss'],
                収支=total['net'], 金額利益割合=total['profit_share'],
                二源の金額利益割合={name: value['profit_share'] for name, value in sources.items()},
                二源とも活動場数=int(simultaneous_active.sum()),
                源別場収支相関=float(np.corrcoef(trend, rebound)[0, 1]),
                二源活動場のみ相関=float(np.corrcoef(trend[simultaneous_active], rebound[simultaneous_active])[0, 1]),
                二源とも赤字場数=int(((trend < 0) & (rebound < 0)).sum()),
                一方黒字他方赤字場数=int((trend * rebound < 0).sum()),
                追従赤字に反発黒字場数=int(((trend < 0) & (rebound > 0)).sum()),
                追従赤字から合計黒字場数=int(((trend < 0) & (combined > 0)).sum()),
                追従黒字から合計赤字場数=int(((trend > 0) & (combined < 0)).sum()),
                併用黒字場数=int((combined > 0).sum()), 同上限追従黒字場数=int((control > 0).sum()),
                併用の場収支標本標準偏差=float(np.std(combined, ddof=1)),
                同上限追従の場収支標本標準偏差=float(np.std(control, ddof=1)),
                全31源別場収支=[dict(場=row['session'], 追従=float(a), 反発=float(b), 合計=float(c))
                                    for row, a, b, c in zip(rows, trend, rebound, combined)]))
    # ----------------------------------------
    # 相関は既知標本の記述であり、将来の分散・優位を認定しない。
    proof = dict(
        全合格=True, 根集計SHA256=sha(account_path), 計算コードSHA256=sha(Path(__file__)),
        配分探索=0, 条件変更=0, 新しい売買計算=0, 新未見確認場数=0,
        対象='事前固定済み追従8：反発2、日経16：4。全31既知場の源別実績。',
        行=rows_out,
        解釈=[
            '値動きへ追従する源と、中心から逸脱後の戻りを取る源は異なる思想を持ち、源別売買経路も独立に照合済み。',
            '同じ枚数上限の追従単独より場収支の標準偏差が小さいことは、今回標本の平準化効果を示す。減収と併記し、将来の保証にはしない。',
            '低い相関でも同じ場で赤字になる。日経の回復反発追加では追従赤字を合計黒字へ転じた場は0で、TOPIXでは追従黒字を2場赤字へ変えた。',
            '独立固定枠で売買が変わらないとき、親別金額利益割合は二源の金額で重み付けた平均であり、源の最高値を超えない。',
            '同じ仮説での繰返し損失と、反発確認後の取得価格劣化を改善する必要がある。配分だけでこの源の欠点が消えるとは扱わない。'],
        API取得=0, 実注文=0)
    target = HERE / '固定配分の同時損失と源別相関.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 行数=len(rows_out), 新しい売買計算=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
