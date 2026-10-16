"""根授権の限定診断小射影だけを計画固定後に一読する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parents[1]
NAME = '根へ渡す九条件と六例の限定小結.json'
EXPECTED_SHA = '65942e400ee39afb70b826b4868ed2dd928759dd91ccbcd188d0836ab9a5cb7d'


def main() -> None:
    """
    機能: 指定小射影の読取目的を先に固定し、同bytes保全後にだけJSONを解析する。
    引数: なし。
    返り値: None。原結果、大射影、台帳、入力cache、APIは読まない。
    """
    source = BASE / 'diagnosis' / NAME
    destination = HERE / '同bytes保全' / NAME
    plan_path = HERE / '限定診断の一読監査計画.json'
    HERE.mkdir(parents=True, exist_ok=True)
    assert not plan_path.exists() and not destination.exists()
    plan = dict(全合格=True, 目的='九条件の全親及び負親の中値方向と横断と実料の恒等式、六例BBO、支持線当行群を独立検算する。',
                対象path=source.relative_to(ROOT).as_posix(), 対象SHA256=EXPECTED_SHA,
                対象上限bytes=100000, 対象原読取回数=1,
                大射影40MB=0, 診断集計138KB=0, 原金融結果=0, 入力cache=0, 台帳=0, API=0, 新金融=0,
                限界=['事後の実完結親だけの診断。入口正答率にしない。', '中値約定や別出口の救済PLは算出しない。',
                     '支持線の当行初期線非喪失は保有継続成功を示さない。'])
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw = source.read_bytes()
    assert len(raw) <= plan['対象上限bytes']
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SHA
    destination.parent.mkdir()
    destination.write_bytes(raw)
    (HERE / '限定診断の一読保全.json').write_text(json.dumps(dict(全合格=True,
        計画SHA256=hashlib.sha256(plan_path.read_bytes()).hexdigest(), SHA256=EXPECTED_SHA, bytes=len(raw),
        保全path=destination.relative_to(ROOT).as_posix(), 原対象読取回数=1,
        元金融=0, 元台帳=0, 元入力=0, 大射影=0, API=0, 新金融=0), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    value = json.loads(raw)
    print(json.dumps(dict(keys=list(value), data=value), ensure_ascii=False))


if __name__ == '__main__':
    main()
