"""V10の確認ドテンだけに40分の方向確認を加える固定二条件。"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT/'work/research145_engine')]
import config145
import source145
import trader_guard145


def configurations():
    """
    機能: 元V10の待機・枚数・入口・出口を固定し、確認ドテンの許可だけを変更する。
    引数: なし。
    返り値: list[dict]はV16とV17。40分特徴は公開済み列4・6を使用する。
    """
    base = next(x for x in config145.configurations() if x['id'] == 'V10')
    return [dict(base, id='V16', name='V10の確認ドテンに40分差の方向一致', flip_guard40=1),
            dict(base, id='V17', name='V10の確認ドテンに40分差と平均の方向一致', flip_guard40=2)]


def prepare_addons(scene, packet, data, raw, baseline, label):
    """
    機能: 登録後の既知一場入力から追加担当V16/V17の全約定を生成する。
    引数: scene(str)、packet/data/raw/baseline/label(dict)は既存キャッシュ形式。
    返り値: dict[str,ndarray]は追加担当のみの十列約定。事後ラベルは売買へ渡さない。
    """
    assert data['features'].shape[1] == 31
    assert data['ready']['session'] == scene
    config = source145.first143.addon_config(scene, 3)
    return {c['id']: trader_guard145.replay(data, config, c, fee10=0)[0]
            for c in configurations()}
