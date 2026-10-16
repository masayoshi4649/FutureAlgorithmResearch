"""保存型だけを直した診断の再読を、初回失敗履歴と別目的で固定する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE.parent


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 小さな固定資料と同バイト指紋を読む。
    引数: path(Path)は既存の人工・固定・監査・失敗資料。
    返り値: tuple[dict,str]は内容とSHA256。市場cacheは読まない。
    """
    content = path.read_bytes()
    return json.loads(content.decode('utf-8-sig')), hashlib.sha256(content).hexdigest()


def main() -> None:
    """
    機能: 初回66一読を隠さず、同じ33場の保存修正目的の再読を固定する。
    引数: なし。修正版人工513・独立330と全52payloadを確認する。
    返り値: None。新金融・実台帳・原板・APIは起動しない。
    """
    prepare = WORK / 'prepare_v2'
    plan, plan_sha = read(prepare / '元公開と紙上継続窓の非金融一読診断計画.json')
    fixed, fixed_sha = read(prepare / '二cacheの小目録固定.json')
    artificial, artificial_sha = read(prepare / '厳密joinと公開符号及び当時窓接頭の純人工.json')
    audit, audit_sha = read(WORK / 'technical_audit/保存原始型だけの修正と初回読取履歴の独立SOURCE_ONLY接続.json')
    old_fixed, _ = read(WORK / 'prepare/二cacheの小目録固定.json')
    old_false, old_false_sha = read(WORK / 'prepare/診断False.json')
    assert plan_sha == 'd3ca5faf579bfca1460e14c9845999f126e18260e985afe7d9abdeefc9a21b4a'
    assert fixed_sha == '57ad4fa098f7a04d425f308070e4d89d5c9004998e66c7e9c172174318a89825'
    assert artificial_sha == 'df3e254648ef9ef9fbbea0565dc21c644d24bff3cac70d4416a9c3439d70f4c8'
    assert audit_sha == '0f3a164679665eee67e3b2db481b7f80eae1bc302f5d65777f6f24f17c27b2f3'
    assert old_false_sha == 'c84415f12858d5eaf5d33f383b9f62511c6591f45f0768ebd7f5e631f3e55113'
    assert all(item['全合格'] for item in (plan, fixed, artificial, audit))
    assert not old_false['全合格'] and old_false['読取計数']['完了場'] == 33
    assert artificial['検査数'] == 513 and audit['検査数'] == 330
    assert plan['source_SHA256'] == fixed['source_SHA256'] == audit['source_SHA256']
    assert len(plan['source_SHA256']) == 23
    assert fixed['sessions'] == old_fixed['sessions'] and fixed['inputs'] == old_fixed['inputs']
    assert fixed['input_manifests'] == old_fixed['input_manifests']
    assert fixed['計画SHA256'] == plan_sha and fixed['人工SHA256'] == artificial_sha
    for relative, expected in plan['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for relative, expected in plan['source111不変の確認対象'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative

    # ----------------------------------------
    # 同じ33場の新効能と数えず、保存だけを修正した目的を明示する。
    output = HERE / '保存修正後の非金融一読の根固定.json'
    assert not output.exists()
    output.write_text(json.dumps(dict(
        全合格=True, 主体='root', 固定日=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        計画SHA256=plan_sha, 小目録固定SHA256=fixed_sha, 人工SHA256=artificial_sha,
        独立監査SHA256=audit_sha, 初版FalseSHA256=old_false_sha,
        初版本文読取履歴=old_false['読取計数'], source_SHA256=plan['source_SHA256'],
        入力三十三組不変=True, 修正目的='計算・資格不変。NumPy保存型の修正で失われた診断表を再出力。',
        修正後の許可本文読取=66, 同じ対象場数=33, 新金融有効性標本=0,
        金融=0, 実台帳=0, 原板=0, 原NPZ=0, API=0, 自動再開始=False),
        ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    print('保存修正目的の66cache再読を固定。初版履歴保全・新効能証拠0。')


if __name__ == '__main__':
    main()
