"""現在支持源の必要検証と補足が全て合格してから、新損益前の目録へ束ねる。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 完了した前検証の記録を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。保存された合否と参照指紋。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 検査と現行コードの同一性を確認する。
    引数: path(Path)は資料又はコード。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(relative: str) -> dict:
    """
    機能: 合格した証跡と、その計算に使った依存が現在も一致するかを確かめる。
    引数: relative(str)は新99からの資料パス。
    返り値: dict。根からの資料パスと指紋。
    """
    path = HERE / relative
    proof = read(path)
    assert proof.get('全合格', proof.get('合格', False)), relative
    for name, expected in proof.get('SHA256', {}).items():
        assert digest(ROOT / name) == expected, name
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


def main() -> None:
    """
    機能: 新正式損益前に必要な五検査と源境界、保存、接頭の補足を固定する。
    引数: なし。
    返り値: None。未完・不合格・新正式結果作成済みなら目録を保存しない。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    mandatory = {
        '全34人工と支持源政策': 'audit/全34基本人工の候補待機幾何及び独立最初触発と実経済.json',
        '旧十八対照全1116とnull経済': 'audit/旧支持18条件の98全1116口座及び旧20配列と共有入力の完全一致.json',
        '実入力因果不変': 'engine_review/二代表の実接頭と自己相手LP未来及び同clock後続の独立不変.json',
        '結果前独立反証': 'review_pre/34現在支持の局所配線と非包摂及び未来不変の独立反証.json',
        '独立監査人工CLI全8期間の終端': 'audit/人工68口座の独立本番CLIと全8期間及び根会計の保存終端.json'}
    extra = {
        '独立支持数式と取消及び再準備の境界': 'audit/支持源の資格と硬取消及び再準備の独立正負境界.json',
        '買売非対称の支持配線': 'review_pre/現在支持の買売非対称配線の独立補足.json',
        '結果前の独立仕様反証': 'review_pre/34現在支持源の独立仕様反証と局所人工の事前期待値.json',
        '根の全34保存往復と支持源59': 'root_preflight/全34人工の根台帳と支持源及び待機出口診断の保存往復.json',
        '根の実接頭と自己相手未来': 'root_preflight/六代表の実接頭と支持源及び自己相手未来の不変.json',
        '根の独立選定の手算と不正段階拒否': 'root_preflight/二候補と少数親の独立前16選定準備検査.json',
        'PythonとJIT及び実入力指紋の自己検査': 'engine_preflight/全34人工と独立LP支持正負及びPythonJITと59源の自己検査.json'}
    result = dict(全合格=True, 新正式損益未実行=True,
                  検査={name: binding(path) for name, path in mandatory.items()},
                  補足={name: binding(path) for name, path in extra.items()},
                  人工CLIの範囲='通常監査mainと共通独立verify_bundle、根aggregate/stability及びledgerの保存再読込を全68口座/544商品期間で確認。人工31場への水増しはしない。',
                  実入力の範囲='新接続の実72接頭と二代表のLP再投影接頭・自己/相手未来/同時計後続不変。既存LP抽出後の接続検査であり、原JSONL全再生成や真受信順の証明とは区別する。',
                  新診断の範囲='独立LP源と旧BBO源を別59列へ輸送、実際の支持2列の全格子指紋と公開格子診断を分離。旧内部20/観測10と補助10の独立範囲は継承し、全状態の全行再構築へ拡張して呼ばない。',
                  初回人工不一致='未知BBOのsafe0輸送と、C3再準備後の押し不足を誤って正例とした人工期待値を、不合格記録を残して修正。経済状態機械engineは旧98から不変。',
                  API取得=0, 実注文=0)
    (HERE / '前検証目録.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 必要検査数=len(mandatory), 補足検査数=len(extra),
                         新正式損益未実行=True), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
