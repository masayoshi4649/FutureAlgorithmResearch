"""場末会計の限定改訂前の資料と158条件を内容不変で退避する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def digest(path: Path) -> str:
    """機能: 退避前後の実物を照合する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 旧成果をコピーして旧パス対応と再検算規則を固定する。

    引数: なし。返り値: なし (None)。移動・削除・元成果の改変を行わない。
    """
    output=HERE/'cash_revision_v1'
    assert not output.exists(), '退避の上書きを禁止'
    files=[p for p in HERE.iterdir() if p.is_file() and p.suffix in ('.py','.json','.md','.txt')]
    for folder in ('summaries','sessions','ledgers','waves','accounting'):
        files.extend((HERE/folder).glob('*'))
    references={}
    for path in sorted(files):
        assert path.is_file() and path.resolve().is_relative_to(HERE.resolve())
        target=output/path.relative_to(HERE)
        assert target.resolve().is_relative_to(output.resolve())
        target.parent.mkdir(parents=True,exist_ok=True)
        sha=digest(path);shutil.copyfile(path,target)
        assert digest(target)==digest(path)==sha
        references[path.relative_to(ROOT).as_posix()]={'保存先':target.relative_to(ROOT).as_posix(),'SHA256':sha}
    identifiers=sorted(p.stem for p in (output/'summaries').glob('*.json'))
    assert len(identifiers)==158
    for identifier in identifiers:
        for folder,suffix in (('summaries','.json'),('sessions','.json.gz'),('ledgers','.json.gz'),('waves','.json.gz'),('accounting','.json.gz')):
            assert (output/folder/(identifier+suffix)).exists()
    plan=dict(作成日時=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
        原因='固定済みの正遅延と旧会計の即時場末返済要求が衝突。最初の再生は未完了。',
        限定改訂='独立会計の場末2検査領域だけ。注文/入力/数値計算/採否/対象を変えない。',
        旧主条件数=206,旧保存条件数=158,旧保存ID=identifiers,旧補助保存数=0,
        全974再計算必須=True,旧158数値同値必須=True,新旧比較の除外=['summaries.経過秒','summaries.探索固定SHA256'],
        全台帳指紋一致必須=True,全session波accounting完全同値必須=True,
        新方式追加=False,成績による条件除外=False,主仮説差替=False,API取得数=0,
        旧資料=references)
    (HERE/'adaptive_cash_revision_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print('旧資料と158条件をコピー保存。以後の比較規則も固定。')


if __name__=='__main__':main()
