"""v1のusable定義の不足を小人工で再現し、v1証跡を保持してFalseを保存する。"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
import core
import data
import artificial


def normal(value: object) -> object:
    """
    機能: 人工反例を不明はnullの有限JSONへ変換する。
    引数: value(object)は配列、数値、辞書又は列。
    返り値: objectは標準JSON型。
    """
    if isinstance(value, np.ndarray):
        return normal(value.tolist())
    if isinstance(value, dict):
        return {str(name): normal(child) for name, child in value.items()}
    if isinstance(value, list):
        return [normal(child) for child in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    """
    機能: 価格clockが10→5→20となる直前逆行を、単調な出来高時計と分けて反証する。
    引数: なし。
    返り値: None。現v1及び完了metadataは変更せず、金融再生と原本読取は0。
    """
    output = HERE/'v1の価格時計逆行後usableの反例.json'
    assert not output.exists()
    metadata = HERE/'metadata.json'
    assert metadata.exists()
    before = {str((HERE/name).relative_to(ROOT)): data.digest(HERE/name)
              for name in ('core.py', 'data.py', 'prepare.py', 'artificial.py', '入力schema.json',
                           '人工抽出と時計及び欠測と執行対応の検査.json', '原本抽出前の32場登録.json', 'metadata.json')}
    rows = deepcopy(artificial.fixture(4))
    offsets = [0, 10, 5, 20]
    for i, (_, raw) in enumerate(rows):
        raw['CurrentPriceTime'] = artificial.text_time(offsets[i])
        raw['TradingVolumeTime'] = artificial.text_time(0)
    value, diagnosis = core.extract_rows(rows, artificial.START, artificial.END)
    actual = value['volume_delta_usable']
    expected = np.array([False, True, False, False], bool)
    assert actual.tolist() == [False, True, False, True]
    assert value['price_reset_reason'][2] & 8 and value['price_reset_reason'][3] & 64
    assert not value['depth_transition_valid'][3]
    assert value['lp_reset_reason'][3] & 64
    previous_reverse = np.r_[False, (value['price_reset_reason'][:-1] & 8) != 0]
    corrected = actual & ~previous_reverse
    corrected_delta = np.where(corrected, value['volume_delta_observed'], np.nan)
    np.testing.assert_array_equal(corrected, expected)
    assert np.isnan(corrected_delta[3]) and value['volume_delta'][3] == 5
    assert {name: data.digest(ROOT/name) for name in before} == before
    proof = dict(全合格=False, 反例を再現できた=True, v1の最終金融入力採用=False,
        反例=dict(原seq=[0, 1, 2, 3], 価格代理時計の開始後秒=offsets,
                  出来高時計の開始後秒=[0, 0, 0, 0], 公開累計出来高=[100, 105, 110, 115],
                  v1_usable=actual, 期待usable=expected, v1_支持用出来高差=value['volume_delta'],
                  価格reset理由=value['price_reset_reason'], 十段transition資格=value['depth_transition_valid'],
                  LP_reset理由=value['lp_reset_reason']),
        原因='usableのprice_pairは現価格clock逆行を除外するが、直前原行の価格clock逆行を除外していなかった。',
        既人工が見落とした理由='既人工の価格逆行ケースは出来高時計も各原行の元価格clockと一致させていたため、別のvolume時計<=price時計判定で偶然usable=falseとなった。出来高時計を一定にした独立反例が不足。',
        v2派生案=dict(修正列=['volume_delta_usable', 'volume_delta'],
            追加資格='直前price_reset_reasonのclock逆行bit8が0であること。出来高自身のknownや原観測値を変更しない。',
            式='usable_v2 = usable_v1 & ~previous_price_clock_reverse; delta_v2 = where(usable_v2, delta_observed, NaN)',
            人工でのv2_usable=corrected, 人工でのv2_支持用差=corrected_delta,
            元原本再読取=0, 予定='v1原行npzを参照する薄いv2派生loaderと由来manifestを新v2領域へ作り、残る42配列の一致を証明する。まだ正式v2実装実行はしない。'),
        v1終端の範囲='原本SHA・旧正常seq時刻LP両気配対応・全原行保存は完了。usable数理定義の合格とは区別する。',
        保持v1_SHA256=before, 反証source_SHA256=data.digest(Path(__file__)),
        生原本の追加読取=0, 金融再生=0, 現在API取得=0, 実注文=0)
    output.write_text(json.dumps(normal(proof), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('v1 usableの直前価格clock逆行除外不足を再現しFalse保存。v1は変更せず、v2派生案のみ提示', flush=True)


if __name__ == '__main__':
    main()
