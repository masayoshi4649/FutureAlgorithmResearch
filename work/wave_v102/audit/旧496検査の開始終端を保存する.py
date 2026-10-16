"""旧八対照の検査コードを変更せず、開始と終端のソース不変性を保存する。"""

from pathlib import Path
import subprocess
import sys
import traceback

import common


def main() -> None:
    """
    機能: 許可済みの旧496口座検査を一回だけ起動し、金融及び監査ソースの開始終端を照合する。
    引数: なし。根から旧対照検査の実行許可を受けた場合だけ呼ぶ。
    返り値: None。不一致又は検査失敗は別の不合格証跡を保存して例外を送出する。
    """
    paths = [common.BASE/name for name in (
        'engine.py', 'strategy.py', 'data.py', 'catalog.py', 'accounting.py', 'research.py',
        '結果前の設計案.json', '結果前の設計草案.json', '結果前の数理明確化.json')]
    paths += sorted(common.HERE.glob('*.py'))
    start = common.fingerprints(paths)
    beginning = common.HERE/'旧496検査の実行開始.json'
    assert not beginning.exists(), '同じ検査の二重起動を行わない'
    common.save(beginning, dict(
        状態='許可後の実行直前', コマンド='python -X utf8 work/wave_v102/audit/controls.py',
        開始SHA256=start, 対象='金融と監査の現行ソース。旧原本及び旧台帳の重複総走査を追加しない。',
        新正式損益=0, API取得=0, 実注文=0))

    # ----------------------------------------
    try:
        subprocess.run([sys.executable, '-X', 'utf8', str(common.HERE/'controls.py')],
                       cwd=common.ROOT, check=True)
        end = common.fingerprints(paths)
        assert end == start, '旧496検査中に金融又は監査ソースが変更された'
        proof_path = common.HERE/'旧八対照の101全496口座と旧経済及び増玉支持の完全一致.json'
        proof = common.read(proof_path)
        assert proof['合格'] is True and proof['検査件数']['口座'] == 496
        common.save(common.HERE/'旧496検査の開始終端ソース不変.json', dict(
            合格=True, 開始SHA256=start, 終端SHA256=end, 同一=True,
            旧検査証跡=str(proof_path.relative_to(common.ROOT)), 旧検査SHA256=common.sha(proof_path),
            検査件数=proof['検査件数'], 旧固定照合件数=proof['旧101固定依存'],
            旧全台帳の追加二重指紋計算=0, 新正式損益=0, API取得=0, 実注文=0))
        print('旧496口座検査の開始及び終端ソースが一致。', flush=True)
    except Exception as error:
        serial = 1
        destination = common.HERE/f'旧496実行不合格_{serial:05d}.json'
        while destination.exists():
            serial += 1
            destination = common.HERE/f'旧496実行不合格_{serial:05d}.json'
        common.save(destination, dict(
            合格=False, 原因=str(error), 詳細=traceback.format_exc(), 開始SHA256=start,
            終端SHA256=common.fingerprints(paths), 新正式損益=0, API取得=0, 実注文=0))
        raise


if __name__ == '__main__':
    main()
