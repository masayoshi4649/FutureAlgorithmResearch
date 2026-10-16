"""根保存by_sessionの存在に合わせ、比較範囲の説明だけを結果前に訂正する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 主条件・選定順を不変にして、旧ON各場netと未測経路の境界を明記する。
    引数: なし。先の金融前v1(JSON)を保全してv2へ写す。
    返り値: None。新結果・旧金融本文・入力・台帳・APIは読まない。
    """
    source, target = HERE/'報告書選定の事前固定_v1.json', HERE/'報告書選定の事前固定_v2.json'
    assert not target.exists()
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '730060e9c512826a38a401e7479dececf81b25f3dd7b4fd32320d13a20ceac48'
    value = json.loads(raw.decode('utf-8'))
    value['選定対象'] = '新OFF十二条件のみ。旧ON十二条件は候補外の保存比較。全場・上位三除外・買売と保存by_sessionの各場net/親数/数量/容量だけを算術比較。'
    value['比較未測'] = '旧各場の総利益/損失内訳、親共通対応・入口時刻・退出理由・途中全経路は未保存。各場net差の保存存在とは別。'
    value['訂正理由'] = '根が旧小射影のeconomic.by_sessionを確認。比較説明のみ訂正、評価基準・順位は全て不変。'
    value['訂正前v1_SHA256'] = hashlib.sha256(raw).hexdigest()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, v2_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        金融=0, 旧本文=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
