"""NKの数学的同値三条件を同運転引用として分け、比較数は維持する。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent


def main() -> None:
    """
    機能: 基準/順位を変えず、新495・旧保存198・内部同値99の内訳を固定する。
    引数: なし。結果前v1を保全しv2として保存する。
    返り値: None。係数・採否・金融・入力・台帳・API・公開は変更しない。
    """
    source, target = HERE/'報告書選定の事前固定_v1.json', HERE/'報告書選定の事前固定_v2.json'
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '04a404e02a5aa679db13cfd5cfb37210f89676e42bd902612282e0443b900886'
    assert not target.exists()
    value = json.loads(raw.decode('utf-8'))
    value['標本'] = '同じ保存三十三場の既知内探索。TOP九条件＋NK六条件＝新唯一金融495会計、旧PRICE198、同運転NK_VOL25の同値引用99で792比較。別の独立証拠へ数えない。'
    value['同値条件'] = 'NKはVOL_SELECTEDとVOL25が同出口なら共に釣合い0.25で数学的に同値。VOL25三条件の99会計はVOL_SELECTED既運転を引用する。TOPは0.5対0.25なので同値にしない。'
    value['主合格表示'] = '全十二比較の合格数と、商品別の異なる設定数（TOP十二・NK九）による合格数を分ける。NK同値を二つの有効性証拠に数えない。'
    value['訂正前v1_SHA256'] = hashlib.sha256(raw).hexdigest()
    value['改訂理由'] += ' 同値NK三条件は再金融をせず引用する。基準/順位/売買係数は不変。'
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, v2_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        新唯一金融=495, 旧保存=198, 同運転同値引用=99, 比較=792, 金融=0, input=0, ledger=0, API=0, 公開=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
