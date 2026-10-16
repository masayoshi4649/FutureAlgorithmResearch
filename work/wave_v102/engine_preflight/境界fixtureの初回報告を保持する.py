"""保存されなかった初回fixture失敗を、原source未保持のまま履歴として区別する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能: 初回失敗の報告と原source/output欠落をFalse履歴として保存する。
    引数: なし。売買本体又は人工再生を実行せず、既存の修正済資料だけを読む。
    返り値: None。原sourceのSHAを推測して生成せず、後時点の状態を別に結合する。
    """
    destination = HERE / '初回境界fixtureの同格子改変失敗と原証拠未保持.json'
    assert not destination.exists(), '初回履歴を上書きしません。'
    source = HERE / 'edges.py'
    green = HERE / '余裕と据置の拒否及び不利実fillと通常追尾と未知期限場末の少数自己検査.json'
    snapshot = HERE / '初回履歴保存時点で既に修正済みのedges.py'
    assert not snapshot.exists()
    snapshot.write_bytes(source.read_bytes())
    value = dict(全合格=False,
        記録の性質='rootと旧担当の報告に基づく履歴。元の失敗sourceと原例外出力は保存されていない。',
        報告された失敗='初回は支持悪化を同じ公表格子へ入れて過去の追加予約判断まで消した。次格子までquote不明としてfillを待たせ、次格子以後に支持を悪化させるfixtureへ修正した。',
        原不合格source保持=False, 原不合格出力保持=False,
        原不合格sourceSHA256=None, 原例外出力=None,
        失敗の分類='人工fixtureが検査対象の過去予約を変更したため、意図した予約後資格悪化の検査に到達しない。',
        後時点の状態='以下は本履歴を保存した時点の修正済sourceと合格証跡。元の失敗時点のSHAとして扱わない。',
        修正済source=str(source.relative_to(ROOT)),
        修正済sourceSHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
        修正済source写し=str(snapshot.relative_to(ROOT)),
        修正後合格証跡=str(green.relative_to(ROOT)),
        修正後合格証跡SHA256=hashlib.sha256(green.read_bytes()).hexdigest(),
        原source復元=0, 追加人工再生=0, 正式102損益実行=0, API取得=0, 実注文=0,
        記録作成sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    assert json.loads(green.read_text(encoding='utf-8'))['全合格'] is True
    destination.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    assert json.loads(destination.read_text(encoding='utf-8')) == value
    print(json.dumps(value, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
