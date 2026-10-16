"""正式損益前の主変更を、初版保持と同じ20条件及び独立数理へ軽く再接続する。"""

from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
F = Fraction


def module(path: Path, name: str) -> object:
    """
    機能: 定義又は私有Fraction計算器をmainなしで読込む。
    引数: path (Path)、name (str) は対象と一意名。
    返り値: object はモジュール。新旧エンジン又は正式損益は実行しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    answer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(answer)
    return answer


def digest(path: Path) -> str:
    """
    機能: 軽い仕様・純数理の資料だけを指紋化する。
    引数: path (Path) はファイル。
    返り値: str はSHA256。原本全参照の重複確認は行わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def t0_first(proof_math: object) -> list[dict]:
    """
    機能: 通常X1のT0で初回Q1からQ2へ進む単純経路の初期幅余裕を格子で調べる。
    引数: proof_math (object) は私有Fraction格子計算器。
    返り値: list[dict] は買売・両商品・3Bの境界。実活動数又は予測精度ではない。
    """
    answer = []
    for symbol in ('TOPIX', 'NK225'):
        data = proof_math.terms(symbol)
        for multiple in (F(1, 2), F(1), F(2)):
            lower = (2 * multiple - 1) * data['width'] + data['tick'] \
                + (data['proposed_fees'] - data['initial_fees']) / data['value']
            start = math.ceil(lower / data['tick']) * data['tick']
            paired = []
            for side in (1, -1):
                candidates = []
                for offset in range(-1, 4):
                    gain = start + offset * data['tick']
                    base, quote = data['base'], data['base'] + side * gain
                    old = proof_math.scan_stop(data, side, 1, base * data['value'], data['initial_fees'],
                                               base - side * data['width'], quote, False)
                    entry = quote + side * data['tick']
                    cash = (base + entry) * data['value']
                    line = proof_math.scan_stop(data, side, 2, cash, data['proposed_fees'], old, quote, False)
                    current_net = proof_math.net_at(quote, side, 1, base * data['value'], data['initial_fees'], data['value'])
                    proposed_net = proof_math.net_at(quote, side, 2, cash, data['proposed_fees'], data['value'])
                    distance = side * (quote - line)
                    accepted = current_net >= 0 and proposed_net >= 0 and distance >= multiple * data['width']
                    candidates.append(dict(順行幅=gain, 既存線=old, 合成線=line, 停止余裕=distance,
                                           必要幅=multiple * data['width'], 現net=current_net, 提案net=proposed_net, 数学可否=accepted))
                first = next(value for value in candidates if value['数学可否'])
                assert any(value['順行幅'] < first['順行幅'] and not value['数学可否'] for value in candidates)
                paired.append(first['順行幅'])
                answer.append(dict(商品=symbol, 方向=side, B=multiple, 数学必要下限=lower,
                                   呼値丸めと現金条件を含めた例の通過境界=first['順行幅'], S比=first['順行幅'] / data['width'],
                                   候補=candidates,
                                   限定='初回1枚→2枚、1tick spread、現在値=新peak、X1で費用床無効。支持・源更新・時限等は別条件。'))
            assert paired[0] == paired[1]
    return answer


def main() -> None:
    """
    機能: 主の理論変更前後で20設定が同じことと、初版数理が保存されたことを確認する。
    引数: なし。
    返り値: None。新主へ結び直した独立純仕様JSON。金融結果は読まない。
    """
    initial_path = HERE / '初期幅余裕と旧停止線保全の独立仕様反証.json'
    old = json.loads(initial_path.read_text(encoding='utf-8'))
    assert digest(initial_path) == 'f87fac7465853d2b9ca6eaef04f8e50908cd1d135afda4bc39acf349783d5613'
    paths = [Path(__file__), initial_path, HERE / '初期幅余裕と旧停止線保全を独立に反証する.py',
             WORK / 'catalog.py', WORK / '初版catalog.py', WORK / '結果前の設計案.json',
             WORK / '初版結果前の設計案.json', WORK / '正式新損益前の主変更理由.json',
             WORK / '実装前の仕様明確化.json']
    before = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert old['SHA256'][str((WORK / 'catalog.py').relative_to(ROOT))] == digest(WORK / '初版catalog.py')
    assert old['SHA256'][str((WORK / '結果前の設計案.json').relative_to(ROOT))] == digest(WORK / '初版結果前の設計案.json')
    first = module(WORK / '初版catalog.py', '102初版定義保持の独立確認')
    current = module(WORK / 'catalog.py', '102新主定義の独立確認')
    assert first.PRIMARY == 'B1_T1_Q1_X1' and current.PRIMARY == 'B1_T0_Q1_X1'
    assert first.catalog() == current.catalog() and len(current.catalog()) == 20
    reason = json.loads((WORK / '正式新損益前の主変更理由.json').read_text(encoding='utf-8'))
    assert reason['変更前'] == first.PRIMARY and reason['変更後'] == current.PRIMARY
    assert reason['正式102損益'] == reason['現在API取得'] == reason['実注文'] == 0
    oracle = module(HERE / '初期幅余裕と旧停止線保全を独立に反証する.py', '102私有数理の主変更後確認')
    assert oracle.plain(oracle.cases()) == old['数学例']
    assert oracle.plain(oracle.late_participation()) == old['単純経路で追加が遅くなる必要閾値']
    first_t0 = t0_first(oracle)
    assert len(first_t0) == 12
    after = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    assert before == after
    proof = dict(全合格=True, 初版証跡及びsource保持=True, 全20設定一覧不変=True,
                 変更前の理論主=first.PRIMARY, 変更後の理論主=current.PRIMARY,
                 変更の範囲='正式102損益前の理論主だけ。T1も全20一覧に保持し、利益を見て主を差し替えていない。',
                 独立T1数学20方向例の再一致=True, T1必要閾値8例の再一致=True,
                 T0初回追加の単純経路境界=first_t0,
                 留保='T0は旧線を寄せることを許す。S余裕を満たしても次反転やfill悪化を防ぐ予測ではなく、初回確度を変えていない。',
                 金融成功の認定=False, 正式102損益閲覧=0, 新102売買実行=0,
                 原本の重複hash=0, 旧101編集=0, API取得=0, 実注文=0, SHA256=after)
    output = HERE / '新主T0と保持した初版及び20条件の損益前独立再結合.json'
    assert not output.exists()
    output.write_text(json.dumps(oracle.plain(proof), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 理論主=current.PRIMARY, SHA256=digest(output), 正式102損益=0), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
