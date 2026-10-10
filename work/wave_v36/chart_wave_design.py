"""全429条件の波と、成績で変更しない4方式104図の検査を結果前に固定する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
from zoneinfo import ZoneInfo

import band_design
import band_runner as runner


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METHODS = {'Q034__V000': '気配維持・出来高代理', 'Q007__V000': '純価格の対応対照',
           'Q016__V000': '全出来高代理の対応対照', 'H019__V000': '旧H019・固定A0'}


def prepare() -> dict:
    """機能: 損益を読まず全指定波・図示対象・独立検算の範囲を固定する。

    引数: なし。返り値: 固定記録 (dict)。既存内容との差は拒否する。
    """
    inputs = pickle.loads((HERE.parent/'wave_v23/inputs.pkl').read_bytes())
    specs = [dict(destination='',spec=s) for s in band_design.conditions()]
    specs += [dict(destination='supplementary',spec=s) for s in band_design.supplementary_conditions()]
    assert len(specs) == 429 and len({r['spec']['id'] for r in specs}) == 429
    files = [Path(__file__), HERE/'band_design.py', HERE.parent/'wave_v33/engine_dynamic_atr.py',
             HERE.parent/'wave_v35/wave_order_audit.py', HERE.parent/'wave_v33/chart_data_audit.py',
             HERE.parent/'wave_v23/chart.js', HERE.parent/'wave_v23/inputs.pkl']
    value = dict(対象=specs,主条件数=364,補助条件数=65,全条件数=429,
        指定波=list(runner.base.wave_metrics.EPISODES),全指定波数=3432,比較境界数=6864,
        図示対象=METHODS,全図示数=104,期間=sorted({k[0] for k in inputs}),
        対象選択='Q034主仮説、同W/枝/peerの価格Q007・全量Q016、旧H019を成績前に固定。',
        波検算='主364と補助65を区別して全件。全注文から現金・買い在庫・売り在庫を積算、全返済から実現PLを計算。原本asofで開始/終了時価と正逆時間・枚数分・全区間注文・20分目安・summary通過数を照合。SHAだけの検査ではない。',
        波の限界='指定4波は初期6内の既知目的適合参考。全13も後7も未知ではない。補助は別診断で主の独立標本数へ加えない。',
        図検算='4方式26入力を旧v33固定A0で詳細再生し、全6結果の保存指紋・全4保存台帳・損益/枚数へ照合。全約定を図と表に保持。',
        価格線='5分時計以下の最後の原本行を参照。組が違う又はフラットでは接続しない。線は判断後の値で次原本行から有効。独立の原本/返済式でも検算する。',
        注文起点='旧ordersの発注元行は追跡入口の最終価格更新を含み、初回準備行とは限らない。最新episodeを遡って注文所有へ帰属しない。価格準備/確認/採否は独立の参考表で表示。',
        足='読み取り専用の確定5分足。新規/返済の点は原本行の約定時刻と指定約定価格、部分返済を省略しない。',
        表示='ダーク、短い冒頭、凡例と執行条件は折畳み。104選択の描画・ローカルリンク・全データを照合。',
        新損益読取=False,API取得数=0,現在保存物使用=False,
        参照SHA256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    path=HERE/'chart_wave_fixed.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        assert {k:v for k,v in old.items() if k!='固定日時'}==value
        return old
    value['固定日時']=datetime.now(ZoneInfo('Asia/Tokyo')).isoformat()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return value


if __name__=='__main__':
    prepare()
    print('全429条件・3432波・6864境界、4方式104図を結果前固定。')
