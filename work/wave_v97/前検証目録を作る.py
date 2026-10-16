"""正式損益前の人工・旧対照・因果・敵対的検査を現在実装へ結びつける。"""

import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import research


def binding(path: Path) -> dict:
    """
    機能: 合格した検査資料と参照実装の現在指紋を照合する。
    引数: path(Path)はプロジェクト内の合格JSON。
    返り値: dict。根からの相対資料パスとSHA256。
    """
    path = path.resolve()
    assert path.is_relative_to(research.ROOT.resolve())
    proof = research.read(path)
    assert proof.get('全合格', proof.get('合格', False)), path.name
    for relative, expected in proof.get('SHA256', {}).items():
        assert research.data.digest(research.ROOT / relative) == expected, relative
    return dict(資料=str(path.relative_to(research.ROOT)), SHA256=research.data.digest(path))


def main() -> None:
    """
    機能: 5種類の必須前検査と根保存・JIT・選定準備を正式計算前に保存する。
    引数: CLIの--artificial/--causal/--cli/--jit(Path)は実際の完了資料。
    返り値: None。未完検査又は既存正式結果を拒否する。
    """
    parser = argparse.ArgumentParser()
    for name in ('artificial', 'causal', 'cli', 'jit'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    assert not (HERE / '前検証目録.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    required = {
        '全36人工と待機幾何': args.artificial,
        '旧四出口全248とnull経済': HERE / 'audit/即時四出口の96全248口座及び旧15台帳と候補の完全一致.json',
        '実入力因果不変': args.causal,
        '結果前独立反証': HERE / 'review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.json',
        '独立監査人工CLI全8期間の終端': args.cli}
    supplements = {
        '根台帳の実保存': HERE / 'root_preflight/全36人工の根台帳と待機及び出口診断の保存往復.json',
        'PythonとJITの一致': args.jit,
        '独立選定の準備': HERE / 'root_preflight/二候補と少数親の独立前16選定準備検査.json',
        '既存入力の実接頭と新5入力': HERE / 'root_preflight/五代表の実接頭と新待機及び自己相手未来の不変.json',
        '取消と未知ペアの意味境界': HERE / 'audit/待機取消及び未知ペア時計と押し位相の少数正負と全経済.json',
        '結果前の仕様反証': HERE / 'review_pre/固定36仕様の数理状態定義の完了確認.json'}
    research.save(HERE / '前検証目録.json', dict(
        全合格=True, 新正式損益未実行=True,
        検査={name: binding(path) for name, path in required.items()},
        補足={name: binding(path) for name, path in supplements.items()},
        全31既知=True, 未見確認場数=0, API取得=0, 実注文=0))
    print('5必須検査と6補足を現在実装へ照合。正式新条件損益は未実行。', flush=True)


if __name__ == '__main__':
    main()
