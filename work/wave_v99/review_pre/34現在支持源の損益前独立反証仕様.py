"""現在支持だけを替える34条件の一軸性と局所反証の期待値を正式損益前に保存する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def digest(path: Path) -> str:
    """
    機能: 読取専用の設計及びコードを内容指紋へ対応させる。
    引数: path(Path)。
    返り値: strはSHA256。旧領域と根仕様を変更しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name: str, path: Path) -> object:
    """
    機能: main又は売買を呼ばず定義と既存公開順の数理だけを取り込む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。新正式損益を開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def support(returns: tuple[float, float], side: int = 1,
            execution: tuple[bool, bool] = (True, True),
            window: tuple[bool, bool] = (True, True),
            lp_current: tuple[bool, bool] = (True, True),
            lp_value: tuple[float, float] = (4000., 70000.),
            sufficient: tuple[bool, bool] = (False, False),
            ofi: tuple[float, float] = (0., 0.)) -> bool:
    """
    機能: L1価格資格と旧OFI拒否の独立人工数理を返す。
    引数: returns/LP値/OFI(tuple[float,float])、side(int)、資格群(tuple[bool,bool])。
    返り値: bool。現支持は成績又はOFIの買売支持を意味しない。
    """
    progress = [side * x for x in returns]
    observable = all(execution) and all(window) and all(lp_current)
    observable &= all(np.isfinite(x) and x > 0 for x in lp_value)
    observable &= all(np.isfinite(x) and x > 0 for x in progress)
    observable &= min(progress) >= .25 * max(progress)
    reverse = any(known and side * ratio <= -.1 for known, ratio in zip(sufficient, ofi))
    return bool(observable and not reverse)


def main() -> None:
    """
    機能: カタログの不変部品と支持正負の数理を確認し実装前の期待値を保存する。
    引数: なし。
    返り値: None。正式99売買・損益・現在APIを実行又は閲覧しない。
    """
    catalog = module('現在支持99の固定候補だけ読取', BASE / 'catalog.py')
    values = catalog.catalog()
    assert len(values) == len({v['id'] for v in values}) == 34
    assert catalog.PRIMARY == 'L1_C1_A7_X3' and catalog.CONTROL == 'L0_C1_A7_X3'
    allowed = {'id', 'previous_clock_id', 'entry_support_lane'}
    for value in values:
        old = catalog.PREVIOUS[value['previous_clock_id']]
        assert {k: v for k, v in value.items() if k not in allowed} == {k: v for k, v in old.items() if k not in allowed}
        if value['entry_wait_kind'] == 0:
            assert value['entry_support_lane'] == 'L0'
    by_id = {v['id']: v for v in values}
    for value in values:
        assert all(other in by_id for other in catalog.references(value['id']))
        if value['id'].startswith('L1_'):
            old = by_id[value['id'].replace('L1_', 'L0_', 1)]
            assert {k: v for k, v in value.items() if k not in ('id', 'entry_support_lane')} == \
                {k: v for k, v in old.items() if k not in ('id', 'entry_support_lane')}
    assert support((8., 2.)) and not support((8., 1.999))
    assert not support((0., 2.)) and not support((np.nan, 2.))
    assert not support((8., 2.), sufficient=(True, False), ofi=(-.1, 0.))
    assert support((8., 2.), sufficient=(False, False), ofi=(-.5, 0.))
    assert not support((8., 2.), execution=(False, True))
    assert not support((8., 2.), window=(False, True))
    assert not support((8., 2.), lp_current=(False, True))
    assert not support((8., 2.), lp_value=(np.nan, 70000.))
    # L0の有効変位とL1の有効変位は別の観測であり、包摂を仮定しない。
    assert support((8., 2.)) and not support((-8., -2.))
    numerical = 12
    cases = [
        dict(id='L1のみ支持可能', 条件='旧mid300窓不明、正常LP300は両方向正で比率正常、旧BBO正常',
             期待='L0は待つがL1は後続原行で価格幾何と両BBO条件が成立すれば発注。候補を新作しない。'),
        dict(id='L0のみ支持可能', 条件='旧midは方向支持、正常LPは反対又は一方零',
             期待='L1はL0の上位集合でない。L0の勝ちを消す反例を全会計へ含める。'),
        dict(id='L1の比率境界', 条件='方向付き変位8bp/2bp又は8bp/1.999bp',
             期待='25%等号は許可、未満は不可。方向零は不可。公差を追加しない。'),
        dict(id='LP現在又は窓が不明', 条件='LP値NaN/0、current.valid=False又は300窓source_valid=False',
             期待='支持False。旧boolで救済しない。待機幾何は更新しても支持が正常復帰するまで発注しない。'),
        dict(id='LP正常でも執行板不明', 条件='両LPは正常、旧execution.current.valid又は自己qok/qualityが不正',
             期待='価格だけで旧BBO/品質を救済しない。current.validは支持、自己qok/resetは旧取消で別に拒否。'),
        dict(id='十分な逆OFIと未知OFI', 条件='源有効・OFI有効・非零3以上・比有限で方向付き比−.1／同値がOFI不明',
             期待='十分な逆OFIだけ支持を拒否。未知OFIを支持へ変えないが未知だけで追加拒否も足さない。'),
        dict(id='旧硬い反対と新支持の競合', 条件='L1支持True、旧wait_opposite=True',
             期待='旧mandatoryの硬い反対取消が発注及びC3再準備より先。LPで旧取消を救済しない。'),
        dict(id='C3再準備の支持差', 条件='gap後両新源は正常、L0 False/L1 True又はその逆',
             期待='同じ支持差が再準備時点にも作用。L1を最終入口だけの効果と説明しない。元候補・W・TTLは保持。'),
        dict(id='同時計後続LPは救済に使わない', 条件='あるclock先頭LP不正、同clock後続だけ正常',
             期待='既存asofは厳密過去の最新clock先頭だけ。不正先頭を後続や古い正常源へ差替えない。'),
        dict(id='参照clockと等しい源は未来側', 条件='LP又はpeer時刻が参照期限と同値',
             期待='既存strict過去と同clock先頭を保持。自己rawseq増加を相手の新公表証拠にしない。'),
        dict(id='既存候補なし／同時に枠占有', 条件='支持Trueでもeventが0又は待機・市場予約・保有で枠占有',
             期待='支持だけで新候補を発生させず、消費したpulseは後で支持が正常化しても復活しない。'),
        dict(id='未知LP復帰とC3の再準備同行禁止', 条件='一行後にL1が復帰しC3再準備成立',
             期待='再準備行は発注禁止、A7は押しを再度待つ。タイムアウト又は場末は従来優先。'),
        dict(id='共有preparedとA0旧null', 条件='L0/L1を同じpreparedから交互にplay',
             期待='共有旧entry_j2とtrend_lp_allowedを変更せず浅copy二列だけ接続。A0はL0のまま旧20出力一致。'),
        dict(id='自己・peer未来改変と支持診断公開範囲', 条件='切断後のLP/支持/peer/価格を変形',
             期待='過去の旧20配列及び公表済み支持59診断が不変。未公表gridを出力しない。真受信因果順の証明ではない。'),
    ]
    assert len(cases) == 14
    asof = module('固定94の同時計先頭公開順だけ独立読取99', ROOT / 'work/wave_v94/inputs_r1/strict_board.py')
    times = np.array([100., 100., 101., 102.])
    invalid_first = np.array([False, True, True, True])
    sources, _ = asof.asof_indices(np.array([100., 100.5, 101., 101.5]), times, invalid_first, np.zeros(4, bool))
    np.testing.assert_array_equal(sources, [-1, -1, -1, 2])
    plan = json.loads((BASE / '結果前の設計案.json').read_text(encoding='utf-8'))
    assert plan['予定条件数'] == 34 and plan['理論主'] == catalog.PRIMARY and plan['正式新条件売買実行'] == 0
    value = dict(全合格=True, 状態='99正式損益前の独立仕様反証。実装は完成後の別証跡で検査。',
        条件数=34, 主=catalog.PRIMARY, 対照=catalog.CONTROL, 旧完全一致対照数=18,
        変更の範囲='現在entry_j2の2列だけ。C3では同じ列が再準備時点にも作用する。',
        不変部品='P0旧J8候補、旧hardopposite、Q/OFI/BBO、四時計政策、幾何・TTL・枠・数量・出口・費用・次正常BBO約定。',
        必要人工期待値=cases, 支持数理反証=numerical,
        同時計先頭と厳密過去人工=dict(時刻=times.tolist(), 資格=invalid_first.tolist(),
            参照=[100., 100.5, 101., 101.5], 期待源=[-1, -1, -1, 2]),
        説明の反証=[
            'L1は旧価格観測の欠測解消だけではない。LastPriceとmidの値及び採用源が異なり、旧支持を拒む場合もある。',
            '窓が可観測なこと、判断方向に進んだこと、その先が儲かることは別。候補数又は活動が増えただけで有効とは呼ばない。',
            '同じ元候補の建値/出口/料金差、旧固有の勝負、新固有の勝負、後続経路を全額へ含める。',
            '現在J2をLPへ替えても旧midによる硬い反対取消が残る。取消との競合を成功条件から隠さない。',
            '全31既知。新同時計支持公開は既存strict過去/同clock先頭という代理順内の仕様で、真受信時計や二市場の実受信順は証明不可。',
            'ユーザーの安定性は赤字額だけでなく活動黒字率・赤字場数・平均最大赤字・下方偏差・最大利益日除外で判定。無取引は勝ちなし。'],
        未検証='真受信時計、実注文、未知場、旧硬反対をLPへ変更、板品質救済、数量配分変更。',
        catalog_SHA256=digest(BASE / 'catalog.py'), 根仕様SHA256=digest(BASE / '結果前の設計案.json'),
        安定性指定SHA256=digest(BASE / 'セッション安定性の事前評価.json'),
        計算コードSHA256=digest(Path(__file__)), 新正式損益閲覧=0, 新正式売買実行=0,
        API取得=0, 実注文=0, 旧固定編集=0)
    target = HERE / '34現在支持源の独立仕様反証と局所人工の事前期待値.json'
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('現在支持源34条件の一軸性と14局所期待値を損益前に保存。新正式PLは0。', flush=True)


if __name__ == '__main__':
    main()
