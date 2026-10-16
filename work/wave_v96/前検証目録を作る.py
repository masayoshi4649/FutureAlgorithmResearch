"""必要な独立前検証と現在のコードを指紋で結び、正式再生前に固定する。"""

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research


def binding(relative: str) -> dict:
    """
    機能: 合格証跡と参照した全コードの現在指紋を照合する。
    引数: relative(str)は96領域又は新設計領域の証跡。
    返り値: dict。合格証跡への相対パスとSHA256。
    """
    path = research.ROOT / relative
    proof = research.read(path)
    assert proof.get('全合格', proof.get('合格', False)), relative
    for name, expected in proof.get('SHA256', {}).items():
        assert research.data.digest(research.ROOT / name) == expected, name
    return {'資料': relative, 'SHA256': research.data.digest(path)}


def main() -> None:
    """
    機能: 人工・旧対照・実接頭・敵対的レビューの4区分を正式前に照合する。
    引数: なし。
    返り値: None。正式結果が作成済みなら固定目録の作成を拒否する。
    """
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    paths = {
        '全18人工と出口幾何': 'work/wave_v96/audit/全18人工価格経路と独立出口及び料金と未来不変.json',
        '旧全62とnull経済': 'work/wave_v96/audit/旧S40_M0_H30のJ8全62口座及び候補と経済の完全一致.json',
        '実入力因果不変': 'work/wave_v96/audit/4代表の実接頭と独立出口及び自己相手未来の不変.json',
        '結果前独立反証': 'work/wave_v96/review_pre/初期停止と利益床の局所独立反証.json'
    }
    additional = {
        '根台帳の実保存': 'work/wave_v96/root_preflight/全18人工の根台帳と新出口診断の保存往復.json',
        'PythonとJITの一致': 'work/wave_v96/engine_preflight/八人工のPythonとJIT及び停止線と親予約約定診断の自己検査.json',
        '独立選定の準備': 'work/wave_v96/engine_review/二候補と少数親の独立前16選定準備検査.json',
        '独立監査CLIの実保存': 'work/wave_v96/audit/人工1場36口座の独立本番CLIと根台帳及び会計の保存終端.json'
    }
    research.save(HERE / '前検証目録.json', dict(
        全合格=True, 新正式損益未実行=True,
        検査={label: binding(relative) for label, relative in paths.items()},
        補足={label: binding(relative) for label, relative in additional.items()},
        全31既知=True, 未見確認場数=0, API取得=0, 実注文=0))
    print('4区分と補足4区分の前検証が現在実装に一致しました。', flush=True)


if __name__ == '__main__':
    main()
