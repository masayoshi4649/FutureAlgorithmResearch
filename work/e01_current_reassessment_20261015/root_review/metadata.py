"""今回の独立売買に必要な保存済み小目録と比較基準だけを一読する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PUBLIC = ROOT / 'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
FIXED = ROOT / 'work/e01_opportunity_trace_20261015/prepare_v2/二cacheの小目録固定.json'
BASE = ROOT / 'アルゴリズム調査/00111_少ない価格票で注文価格を追わない検証/価格票の最低数別E01の全場会計.json'
BASE_SHA = 'e543125b8ec2a8f625885aaf912a2f7c441d0a151153fe8d2af0f47a21bc4e27'


def read_once(path: Path) -> tuple[dict, str]:
    """
    機能: 目的を限定した小資料を一度読んだ同じbytesから解析と指紋を作る。
    引数: path(Path) は保存目録又は保存済み公開会計。
    返り値: tuple[dict,str] は内容とSHA256。大型入力を開かない。
    """
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8')), hashlib.sha256(raw).hexdigest()


def main() -> None:
    """
    機能: 元33場の入力目録と旧SEL_TARGET比較を新目的の所有域へ保全する。
    引数: なし。
    返り値: None。cache・NPZ・原板・API・旧台帳を読まない。
    """
    target = HERE / '旧三十三場の入力と保存基準の一読目録.json'
    assert not target.exists()
    intent = HERE / '小目録読取の目的.json'
    assert not intent.exists()
    intent.write_text(json.dumps(dict(
        目的='新しい全normal独立入口の入力指紋を00112修正版fixedから継承し、00111保存基準だけを再利用する。',
        入力=[FIXED.relative_to(ROOT).as_posix(), BASE.relative_to(ROOT).as_posix()],
        読取予定=dict(修正版fixed=1,旧公開会計=1,大型cache=0,原板=0,NPZ=0,旧台帳=0,API=0,新金融=0),
        対照='保存済みSEL_TARGETは複数部品が違う参考。新9経済条件の一部として再金融しない。',
        新二場='2026-10-13_Night・2026-10-14_Dayの価格数量は未読保持。'
    ), ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    fixed, fsha = read_once(FIXED)
    base, bsha = read_once(BASE)
    assert bsha == BASE_SHA
    payload = dict(全合格=True,入力の固定=fixed,保存比較=base,
        出典=[dict(path=FIXED.relative_to(ROOT).as_posix(),SHA256=fsha),
              dict(path=BASE.relative_to(ROOT).as_posix(),SHA256=bsha)],
        読取=dict(修正版fixed=1,旧公開会計=1,大型cache=0,原板=0,NPZ=0,旧台帳=0,API=0,新金融=0))
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(保存=target.relative_to(ROOT).as_posix(),目録キー=list(fixed),
                         比較キー=list(base),出典=payload['出典'],読取=payload['読取']), ensure_ascii=False))


if __name__ == '__main__':
    main()
