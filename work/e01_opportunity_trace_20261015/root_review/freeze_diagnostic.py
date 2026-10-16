"""元公開後の窓資格の非金融診断を、独立検査と入力指紋へ接続する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE.parent
PREPARE = WORK / 'prepare'


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 固定済みの小JSONを一度読み、その指紋と内容を取得する。
    引数: path(Path)は人工・計画・小目録固定・独立監査。
    返り値: tuple[dict,str]は内容とSHA256。大型cache本文は読まない。
    """
    content = path.read_bytes()
    return json.loads(content.decode('utf-8-sig')), hashlib.sha256(content).hexdigest()


def main() -> None:
    """
    機能: 二cache66一読の目的・境界・23源を根の固定記録へ保存する。
    引数: なし。人工509と独立6638を接続する。
    返り値: None。実行自体・金融・台帳・NPZ・API読取は行わない。
    """
    plan, plan_sha = read(PREPARE / '元公開と紙上継続窓の非金融一読診断計画.json')
    fixed, fixed_sha = read(PREPARE / '二cacheの小目録固定.json')
    artificial, artificial_sha = read(PREPARE / '厳密joinと公開符号及び当時窓接頭の純人工.json')
    audit_path = WORK / 'technical_audit/当時窓と厳密結合及び分母の独立SOURCE_ONLY監査.json'
    audit, audit_sha = read(audit_path)
    assert plan_sha == '77393676dcfa6ceb8d4a9558a18210462de3bb2ee32fb8a5bfe4fa73f859f460'
    assert fixed_sha == '2892b5ff395ab87d13f4740e1495b3029ddad3f1f46e854dcf94db43509a5361'
    assert artificial_sha == '65cb800d28897035b51ff9f484eeab50ade455ab402a87c190f737101c4be7e8'
    assert audit_sha == 'c4fe2280ab519a869db84b2b6f3e41ae6267bd062fc368c04ed7d168e32cf335'
    assert all(x['全合格'] for x in (plan, fixed, artificial, audit))
    assert artificial['検査数'] == 509 and audit['検査数'] == 6638
    assert plan['source_SHA256'] == fixed['source_SHA256'] == audit['source_SHA256']
    assert len(plan['source_SHA256']) == 23
    assert fixed['計画SHA256'] == plan_sha and fixed['人工SHA256'] == artificial_sha
    for relative, expected in plan['source_SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    for relative, expected in plan['source111不変の確認対象'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    assert len(plan['source111不変の確認対象']) == 17
    assert len(fixed['sessions']) == len(set(fixed['sessions'])) == len(fixed['inputs']) == 33
    assert plan['大型本文予定']['TradeGatecache'] == plan['大型本文予定']['TradeExitcache'] == 33
    assert all(audit['読取'][key] == 0 for key in ('cache', 'NPZ', '金融本文', '金融', '実台帳', '原board', 'API'))

    # ----------------------------------------
    # 指紋を束縛した旧資料を再生せず、観測資格だけを一読診断する。
    output = HERE / '非金融一読の根固定.json'
    assert not output.exists()
    output.write_text(json.dumps(dict(
        全合格=True, 固定日=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        主体='root', 計画SHA256=plan_sha, 小目録固定SHA256=fixed_sha,
        人工SHA256=artificial_sha, 独立監査SHA256=audit_sha,
        source_SHA256=plan['source_SHA256'], source111不変=True,
        範囲='TradeGate33＋TradeExit33各一読。紙上公開と後の当時窓資格、全normal両方向の別母集団。',
        許可された本文読取=66, 元金融本文=0, 実台帳=0, 原板=0, 原NPZ=0, API=0,
        金融=0, 新アルゴ勝率='未測。資格の観測数は取引機会・正答率・利益ではない。',
        限界='原行/代理時計接続の確認。真の受信順、主体、建玉原価、FAK後実状態は未測。',
        自動再開始=False), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    print('根の非金融66cache一読を固定。入力本文はまだ0。')


if __name__ == '__main__':
    main()
