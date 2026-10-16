"""正式損益を開かず、元候補からの不利幅と固定34対照を数理的に反証する。"""

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]


def module(name: str, path: Path) -> object:
    """
    機能: mainと正式素材を開かず条件定義だけを読み込む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。過去領域へ保存しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 事前計画と根拠を内容指紋で固定する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cap_oracle(candidate: float, quote: float, side: int, width: float,
               multiple: float | None) -> bool:
    """
    機能: 執行源を救済せず正常価格に対する方向付き不利幅の数理条件を独立計算する。
    引数: candidate/quote/width(float)、side(int:1/-1)、multiple(float|None)。
    返り値: bool。Noneは上限無効であり零幅を意味しない。
    """
    known = (side in (-1, 1) and math.isfinite(candidate) and candidate > 0
             and math.isfinite(quote) and quote > 0 and math.isfinite(width) and width > 0)
    return bool(known and (multiple is None or side * (quote - candidate) <= multiple * width))


def main() -> None:
    """
    機能: 34条件の固定部品及び数学上限の正負を確認し実装前期待値を保存する。
    引数: なし。金融入力と新正式売買及び損益を一切開かない。
    返り値: None。自担当review_preだけへ日本語JSONを保存する。
    """
    plan_path = BASE / '結果前の設計案.json'
    handoff = ROOT / 'work/wave_v99/99正式終端と100候補価格上限の未実行引継ぎ.json'
    assert digest(handoff) == '161f4aeea9a29cbeff3c97c34aa633cc2c38ab2074d77601309e49b9b0d25e9a'
    fixed = module('100候補価格上限の独立条件定義', BASE / 'catalog.py')
    old = module('99条件だけを独立読取100', ROOT / 'work/wave_v99/catalog.py')
    configs = {value['id']: value for value in fixed.catalog()}
    old_configs = {value['id']: value for value in old.catalog()}
    assert len(configs) == 34 and fixed.PRIMARY == 'P1_L1_C1_A1_X1'
    assert fixed.CONTROL == 'P0_L1_C1_A1_X1'
    controlled = 0
    for value in configs.values():
        previous = old_configs[value['previous_support_id']]
        rest = {key: item for key, item in value.items() if key not in (
            'id', 'previous_support_id', 'entry_price_cap_name', 'entry_price_cap_multiple')}
        assert rest == {key: item for key, item in previous.items() if key != 'id'}
        assert value['entry_price_cap_multiple'] == dict(fixed.CAPS)[value['entry_price_cap_name']]
        assert all(ident in configs for ident in fixed.references(value['id']))
        controlled += 1

    # ----------------------------------------
    # 半幅を呼値へ切り上げず、買売反射と有利価格と上限等号を独立計算する。
    cases = []
    for side in (-1, 1):
        for multiple in (None, .5, 1., 2.):
            width = 4.5
            for adverse in (-20., 0., 2., 2.25, 2.5, 4.5, 9., 9.5):
                quote = 4500. + side * adverse
                expected = multiple is None or adverse <= multiple * width
                assert cap_oracle(4500., quote, side, width, multiple) == expected
                cases.append(dict(方向=side, 倍率=multiple, W=width,
                    方向付き不利幅=adverse, 上限=None if multiple is None else multiple * width,
                    判定期待=expected))
    assert cap_oracle(4500., 4502., 1, 4.5, .5)
    assert not cap_oracle(4500., 4502.5, 1, 4.5, .5)
    assert cap_oracle(4500., 4500., 1, 4.5, 0.)
    assert not cap_oracle(4500., 4500.5, 1, 4.5, 0.)
    for bad in (0., -1., float('nan'), float('inf')):
        assert not cap_oracle(4500., bad, 1, 4.5, None)

    # ----------------------------------------
    # 形式的に狭い上限は同一時点の受理集合を減らすが、経済及び活動の単調改善は導かない。
    expected = [
        'P0は旧最終triggerを変更しない。Noneを零幅へ代入しない。',
        '買いはask、売りはbid。有利な負の不利幅を絶対値へ変換しない。',
        'W4.5・P05の上限2.25は2.5へ切り上げない。等号は受理する。',
        'A7は局所extremeからの回復でも、上限基準は元候補quoteを保持する。',
        '上限外ではwatch・元TTL・候補ID・方向・幅・枚数枠を保持し、旧順で幾何更新する。',
        '既存watch中の別pulseは消費され、上限内復帰時に古いpulseを復活しない。',
        '同じ行のcut/TTL/reset/qok/旧硬い反対はcap及びL1支持より優先する。',
        'peer未知・旧支持又はL1支持不成立・気配不進行をcap内という理由で救済しない。',
        '現在判断がcap内でも次正常BBOのfillはcap外になり得る。上限を実指値と呼ばない。',
        '候補と同値でも損失はあり得る。狭い上限は勝ち波や必要な順行確認も除き得る。',
        '拒否後の遅い発注は異なる建値と出口及び次の候補経路を作り、活動が単調減少とは限らない。',
        '未来のfill又はMFEを判断へ戻さず、未来不変は代理公開順内の検査に限定する。',
    ]
    result = dict(全合格=True, 種類='100新正式損益前の有限条件と独立数理反証',
        条件34の旧部品固定確認=controlled, 主=fixed.PRIMARY, 対照=fixed.CONTROL,
        数理買売正負ケース=len(cases), 数理ケース=cases, 実装への事前期待値=expected,
        必要な局所境界=['半呼値正負', '買売の不利方向とask/bid', '有利価格', '候補と局所極値',
            '拒否後再入域と別pulse消費', '元TTL及び取消優先', '支持不明及び未知peer',
            '判断後fill超過', '旧P0少数null', '共有prepared不変', '接頭及び自己peer未来改変'],
        未保証=['正式全620旧対照はaudit担当。ここでは未実行。',
            '価格LP/BBO窓全原本の再構成は既存入力監査の範囲。局所bool注入をその認定へ拡張しない。',
            '真受信時計と二市場の共通受信順は未観測。今回再生時計はCurrentPriceTime由来。',
            '実指値新規、C3上限追加、利益床開始改修及び未見セッションは未測定。'],
        評価の限界='全31既知。無取引を勝ちにせず、平均/最大赤字と黒字率及び活動を同時比較する。'
                    '金額80%又は赤字軽減だけで毎場安定の達成を認定しない。',
        参照SHA256={path.relative_to(ROOT).as_posix(): digest(path) for path in
            (BASE / 'catalog.py', plan_path, handoff, ROOT / 'work/wave_v99/catalog.py')},
        SHA256={path.relative_to(ROOT).as_posix(): digest(path) for path in
            (BASE / 'catalog.py', plan_path, handoff, ROOT / 'work/wave_v99/catalog.py', Path(__file__))},
        計算コードSHA256=digest(Path(__file__)), 新正式損益閲覧=0, 新正式売買実行=0,
        現在API取得=0, 実注文=0, 過去成果編集=0)
    (HERE / '判断価格上限の独立仕様及び局所実装への事前期待値.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('100条件34固定と64買売数理反証が合格。新正式損益0。', flush=True)


if __name__ == '__main__':
    main()
