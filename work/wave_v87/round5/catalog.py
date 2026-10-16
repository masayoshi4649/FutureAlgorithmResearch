"""最新支持の判定方法を保ち、支持強度だけを変える十二条件。"""

from pathlib import Path
import importlib.util
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def catalog():
    """
    機能: 元GU/P1、自己/双方支持、三つの強度を全組合せで返す。
    引数: なし。
    返り値: list[dict] の固定した十二条件。
    """
    path = HERE.parent/'round3/catalog.py'
    spec = importlib.util.spec_from_file_location('wave87_round5_prior_catalog', path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    result = []
    for original in old.catalog():
        if original['support_mode'] not in (1, 3):
            continue
        for label, threshold in [('005', .05), ('025', .25), ('050', .5)]:
            config = dict(original, id=original['id']+'_H'+label,
                          name=original['name']+f'・支持{threshold:g}ATR超',
                          round3_id=original['id'], threshold_atr=threshold,
                          support_scale=.05/threshold)
            config['changes'] = dict(original['changes'])
            result.append(config)
    assert len(result) == 12
    return result


def specification():
    """
    機能: 強度だけの反証、元値と換算値、既知データの制約を明記する。
    引数: なし。
    返り値: dict の固定仕様。
    """
    return dict(
        件数=12, 主仮説=['GU_F1_H025'],
        比較='元GU/P1×自己最新F1/双方最新F3×支持閾値.05/.25/.5ATR。十二条件を変えず全件比較する。',
        変更点='自己と相手の最新公開30秒中値差/当時ATRへ .05/閾値 を掛け、変更しない元判定器の厳密な >.05 条件を使う。',
        基準一致='H005はGU_F1/P1_F1/GU_F3/P1_F3の元値と全配列一致を確認する。',
        強度根拠='.05は既存支持、.25は入口反発幅、.5は既検証の停止幅に由来する粗い対照。最適値の細かい探索ではない。',
        F1='自己の最新有効支持のみを要求。相手30秒支持を追加しない。元GU/P1の中期二市場開始条件は維持。',
        F3='自己と相手の双方で同じ強度を要求。相手は自己時刻より厳密に過去の公開イベントだけ。',
        固定='支持の公開時刻・有効性・30秒窓・原本対応・元TTL・注文公開順・U見送り・出口・数量・料金はround3と同じ。新たな鮮度や極値後条件は足さない。',
        注文順='前観測で公開した注文を現在値で評価した後、今回の支持を次観測の注文許可へ反映。当行の支持低下で当行成立を後から取り消さない。',
        共有配列='preparedはround3を参照し複製しない。playごとに自己値と相手値の配列だけ新しく作り、共有元配列を変更しない。',
        証跡='設定に元条件ID・閾値・倍率を保存。支持変更観測の証跡に元自己/相手値と換算自己/相手値を保存する。',
        既知='全30場も前16/後14も既知。旧台帳の支持強度診断を見た後の原因仮説の反証で、未知研究・未見成功とは呼ばない。',
        評価='取り除けた負けだけでなく、失った勝ち、代替新規、平均勝負比、金額利益割合、最大赤字場、最大下落、日夜と前後期間で比較。旧台帳を削るだけの改善判定はしない。',
        API取得=0, 実注文=0)
