"""価格上限の売買前検証を、合格証跡と保持した不合格履歴に分けて固定する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 保存された合否と依存指紋を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。証跡の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 検査時と現行のコード及び資料を照合する。
    引数: path(Path)は対象ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def binding(relative: str, passed: bool = True) -> dict:
    """
    機能: 未完・指紋不一致の証跡を除き、元の合否を変更せず参照へ束ねる。
    引数: relative(str)は100内のパス、passed(bool)は期待する合否。
    返り値: dict。根相対パスと保存指紋。
    """
    path = HERE / relative
    proof = read(path)
    assert proof.get('全合格', proof.get('合格', None)) is passed, relative
    for name, expected in proof.get('SHA256', {}).items():
        assert digest(ROOT / name) == expected, name
    return dict(資料=str(path.relative_to(ROOT)), SHA256=digest(path))


def main() -> None:
    """
    機能: 新正式損益前の必要五検査と補足及び人工不足の履歴を保存する。
    引数: なし。
    返り値: None。新損益既存、未完検査、指紋不一致なら固定せず停止する。
    """
    assert not (HERE / '事前固定.json').exists()
    assert not list((HERE / 'front/results').glob('*.json'))
    assert not list((HERE / 'back/results').glob('*.json'))
    mandatory = {
        '全34人工と価格上限政策': 'audit/全34基本人工の候補待機幾何及び独立最初触発と実経済.json',
        '旧十対照全620とnull経済': 'audit/上限なし旧十条件の99全620口座と旧20及び支持源の完全一致.json',
        '実入力因果不変': 'engine_review/三代表の実接頭と判断上限及び自己相手LP未来と同clock後続の独立不変.json',
        '結果前独立反証': 'review_pre/判断価格上限の局所状態及び約定超過と未来不変の独立反証.json',
        '独立監査人工CLI全8期間の終端': 'audit/人工68口座の独立本番CLIと全8期間及び根会計の保存終端.json'}
    extra = {
        '独立上限の数式と取消及び元候補保持の境界': 'audit/判断価格上限の等号と保持及び取消と実約定超過の独立境界.json',
        '結果前の独立仕様数理反証': 'review_pre/判断価格上限の独立仕様及び局所実装への事前期待値.json',
        '根の全34保存往復と上限支持源': 'root_preflight/全34人工の根台帳と価格上限及び支持源待機出口診断の保存往復.json',
        '根の実接頭と自己相手未来': 'root_preflight/六代表の実接頭と価格上限支持源及び自己相手未来の不変.json',
        '根の独立選定の手算と不正段階拒否': 'root_preflight/二候補と少数親の独立前16選定準備検査.json',
        'PythonとJIT及び元TTLと実約定超過の自己検査': 'engine_preflight/全34人工と判断上限及び元TTLと約定超過とPythonJITの自己検査.json'}
    failed = {
        '独立人工の複写数値と正例期待の不足': 'audit/初回人工fixtureの文字列置換による数値反射不足.json',
        '根の急上昇しかない人工進行の不足': 'root_preflight/根の初回人工不足.json'}
    value = dict(全合格=True, 新正式損益未実行=True,
        検査={name: binding(path) for name, path in mandatory.items()},
        補足={name: binding(path) for name, path in extra.items()},
        不合格履歴={name: binding(path, False) for name, path in failed.items()},
        上限の意味='発注判断価格の不利幅だけを制限。予約後の次正常気配約定は上限外でも成立し、その超過を別に診断する。実指値新規の証明ではない。',
        人工CLIの範囲='人工68口座/544期間を通常監査mainと共通verify_bundle、根aggregate/stabilityと保存再読込で確認。人工一場を31場へ水増ししていない。',
        実入力の範囲='根72接頭と実3代表24接頭。検査済み素材及びI3端点を保持したLP再投影の新接続の検査。原JSONLから全特徴を再抽出した証明や真の受信順保証ではない。',
        新診断の範囲='上限20列と親21列を独立構成。旧内部20/観測10/補助10、支持59と実2列SHAの継承範囲を別に保持する。',
        人工不足の意味='数値複写と成立期待が不適切な人工を訂正して再実行。金融本体や判定条件をゆるめていない。False資料をFalseのまま保持する。',
        API取得=0, 実注文=0)
    (HERE / '前検証目録.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 必要検査数=len(mandatory), 補足検査数=len(extra),
                         保持した不合格履歴=len(failed), 新正式損益未実行=True), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
