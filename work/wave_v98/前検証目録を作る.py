"""完成した独立前検証だけを凍結の必要証跡へ束ねる。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 完了した前検証又は仕様を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 前検証と現時点のソースを結びつける。
    引数: path(Path)はファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(relative: str) -> dict:
    """
    機能: 合格した検査の参照先と全コード指紋を確認する。
    引数: relative(str)は新98からの証跡相対パス。
    返り値: dict。資料パスと現行SHA256。
    """
    path = HERE / relative
    proof = read(path)
    assert proof.get('全合格', proof.get('合格', False)), relative
    for name, expected in proof.get('SHA256', {}).items():
        assert digest(ROOT / name) == expected, name
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


def main() -> None:
    """
    機能: 五つの必要検査と根の保存・接頭検査を新損益前に束ねる。
    引数: なし。
    返り値: None。未合格又は新正式損益作成済みなら保存しない。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    mandatory = {
        '全34人工と時計政策': 'audit/全34人工と時計政策の独立前検証を束ねた証跡.json',
        '旧十対照全620とnull経済': 'audit/厳密時計10条件の97全620口座及び旧18配列と共有入力の完全一致.json',
        '実入力因果不変': 'engine_review/七代表の実接頭とgap政策及び自己相手未来の独立不変.json',
        '結果前独立反証': 'review_pre/34政策の局所境界とepoch及び未来不変の独立反証.json',
        '独立監査人工CLI全8期間の終端': 'audit/人工68口座の独立本番CLIと全8期間及び根会計の保存終端.json',
    }
    extra = {
        '根の政策台帳保存復元と全8期間': 'root_preflight/全34人工の根台帳と時計政策及び待機出口診断の保存往復.json',
        '根の実接頭と自己相手未来': 'root_preflight/六代表の実接頭と時計政策及び自己相手未来の不変.json',
        '根の独立選定の手算と不正段階拒否': 'root_preflight/二候補と少数親の独立前16選定準備検査.json',
        'PythonとJITの自己検査': 'engine_preflight/gap四政策の少数人工と旧18列及びPythonJITの自己検査.json',
        '独立政策正負及び別epoch': 'audit/少数時計政策の正負及び別epochと最初触発の独立検算.json',
    }
    answer = dict(全合格=True, 新正式損益未実行=True,
        検査={name: binding(path) for name, path in mandatory.items()},
        補足={name: binding(path) for name, path in extra.items()},
        人工CLIの範囲='監査の通常mainと共通verify_bundle、根aggregate/stability、全8期間及び保存終端。根assemble.mainへ人工31場を水増ししていない。正式段で全2108口座の集計と独立照合を行う。',
        実接頭の範囲='同じ不変素材から新接続84接頭、根72接頭と自己相手未来不変。原本再生成40接頭は旧97根拠を継承。実際の二市場受信順の保証ではない。',
        政策診断の独立範囲='独立oracleで内部20状態と観測10源、最初触発及び全経路を再構成。補助flags10は疎保存SHAと少数の意味正負で確認し、全40列の全経路独立再現とは主張しない。',
        API取得=0, 実注文=0)
    (HERE / '前検証目録.json').write_text(json.dumps(answer, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 必要検査数=len(mandatory), 補足検査数=len(extra), 新正式損益未実行=True), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
