"""金融会計が101から不変であることを確認し、既検算を重複実行せず継承する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def digest(path: Path) -> str:
    """
    機能: 会計の同一性と旧証跡を識別する。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 新旧会計のbyte一致と旧の実cohort会計検算合格を結ぶ。
    引数: なし。
    返り値: None。売買本体も会計の再実行も行わない。
    """
    previous = WORK.parent / 'wave_v101'
    proof_path = previous / 'root_preflight/複数実新規と全量返済の人工会計.json'
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全合格']
    assert digest(WORK / 'accounting.py') == digest(previous / 'accounting.py')
    paths = [Path(__file__), WORK / 'accounting.py', previous / 'accounting.py', proof_path]
    output = dict(全合格=True, 不変会計byte一致=True,
        継承範囲='101と同一の実注文別料、整数返済料配分、cohort相殺前金額枚数、親weighted会計。19門番の保存は別検査。',
        会計再実行=0, 正式新損益=0, API取得=0, 実注文=0,
        SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths})
    (HERE / '101不変会計と既人工検算の継承.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print('101不変会計のbyte一致と人工証跡を継承しました。', flush=True)


if __name__ == '__main__':
    main()
