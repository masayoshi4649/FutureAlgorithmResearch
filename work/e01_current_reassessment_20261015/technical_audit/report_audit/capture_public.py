"""公開二成果物だけを各一読し、監査用に同一bytesを保全する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
PUBLIC = ROOT / 'アルゴリズム調査/00113_現在の注文活動と再進行から波の中間に参加'
FILES = ('現在の活動と再進行の公開会計.json', '現在の活動と再進行から参加する手法と全セッション損益.html')


def main() -> None:
    """
    機能: 許可された公開JSONとHTMLを各一読し、parse前の保全と読取目的を残す。
    引数: なし。
    返り値: None。元金融、入力、実台帳、APIは読まない。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    target = HERE / '公開同bytes保全'
    assert not target.exists(), '一読保全済み成果物を上書きしない。'
    target.mkdir()
    purpose = dict(目的='公開十比較の算術とPC及びモバイルDOM表示を独立検査する。',
                   公開会計読取=1, 公開HTML読取=1, 元金融結果=0, 入力cache=0,
                   実台帳=0, API=0, 新金融=0)
    (HERE / '公開二成果物の一読目的.json').write_text(
        json.dumps(purpose, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {}
    for name in FILES:
        source = PUBLIC / name
        raw = source.read_bytes()
        assert len(raw) < 2_000_000
        saved = target / name
        saved.write_bytes(raw)
        manifest[name] = dict(元path=source.relative_to(ROOT).as_posix(),
                              保全path=saved.relative_to(ROOT).as_posix(),
                              SHA256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), 元読取回数=1)
    (HERE / '公開一読と同bytes保全の目録.json').write_text(
        json.dumps(dict(全合格=True, 目的=purpose, 成果物=manifest), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    account = json.loads((target / FILES[0]).read_text(encoding='utf-8'))
    first = next(iter(account['cases'].values()))
    print(json.dumps(dict(目録=manifest, keys=list(account), ケース={key: list(value) for key, value in account['cases'].items()},
                         先頭行=first['rows'][0], 先頭指標=first['metrics'], 会計属性={key: value for key, value in account.items() if key != 'cases'}), ensure_ascii=False))


if __name__ == '__main__':
    main()
