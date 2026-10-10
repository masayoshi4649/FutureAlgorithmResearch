"""セッション終了後に分かる始終方向で、基準J2の既存損益を説明用に分類する。"""

import csv
import hashlib
import io
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX','NK225')
GROUPS = ('双方上昇','双方下落','逆方向','同値含む')
HASHES = {}


def read_json(path):
    """
    機能: 既存の固定資料と費用後会計を読み、指紋を記録する。
    引数: path (Path)。
    返り値: dict は保存内容。
    """
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data.decode('utf-8'))


def direction(session, symbol):
    """
    機能: 保存5分足の当場最初の始値と最後の終値の符号を求める。
    引数: session/symbol (str)。
    返り値: dict は始終時刻、始終値、価格差、収益率、符号。
    この終値は事後説明だけに使い、取引条件へ渡さない。
    """
    path = ROOT/'candle_5min'/symbol/f'{session}.csv'
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    assert rows and [r['time'] for r in rows] == sorted(r['time'] for r in rows)
    initial, final = float(rows[0]['open']), float(rows[-1]['close'])
    assert math.isfinite(initial) and math.isfinite(final) and initial > 0 and final > 0
    difference = final-initial
    return {'始値':initial,'末終値':final,'差':difference,'変化率':final/initial-1,
            '符号':int(difference > 0)-int(difference < 0),
            '最初の保存足時刻':rows[0]['time'],'最後の保存足時刻':rows[-1]['time'],
            '最後の足確定フラグ':rows[-1]['closed'],'保存足数':len(rows)}


def summarize(rows, sessions, symbol):
    """
    機能: 説明群ごとに単一商品の費用後利益・損失と活動を合計する。
    引数: rows (list[dict])、sessions (list[str])、symbol (str)。
    返り値: dict は群別会計。無取引を黒字へ含めない。
    """
    selected = [r for r in rows if r['session'] in sessions and r['symbol'] == symbol]
    assert len(selected) == len(sessions)
    profit = sum(r['profit'] for r in selected)
    loss = sum(r['loss'] for r in selected)
    wins = sum(r['winning_legs'] for r in selected)
    losses = sum(r['losing_legs'] for r in selected)
    return {'場数':len(sessions),'利益':profit,'損失':loss,'収支':profit-loss,
            '平均勝ち平均負け比':(profit/wins)/(loss/losses) if wins and losses else None,
            '総利益総損失比':profit/loss if loss else None,
            '金額利益割合':profit/(profit+loss) if profit+loss else None,
            '黒字場数':sum(r['net'] > 0 for r in selected),
            '赤字場数':sum(r['net'] < 0 for r in selected),
            '無取引場数':sum(r['trades'] == 0 for r in selected),
            '取引あり同値場数':sum(r['trades'] > 0 and r['net'] == 0 for r in selected),
            '取引組数':sum(r['trades'] for r in selected)}


def main():
    """
    機能: 既知30場を始終方向で事後分類し、全体及び前後の会計を保存する。
    引数: なし。
    返り値: None。手法の選定・売買判断・再生は行わない。
    """
    fixed = read_json(HERE/'事前固定.json')
    result = read_json(HERE/'results/J2_F0_B0_H0_R0.json')
    classified = []
    for session in fixed['全30']:
        directions = {s:direction(session,s) for s in SYMBOLS}
        signs = [directions[s]['符号'] for s in SYMBOLS]
        group = '同値含む' if 0 in signs else '双方上昇' if signs == [1,1] else '双方下落' if signs == [-1,-1] else '逆方向'
        money = {s: next(r for r in result['rows'] if r['session'] == session and r['symbol'] == s) for s in SYMBOLS}
        classified.append({'セッション':session,'事後群':group,'始終方向':directions,
                           'J2収支':{s:money[s]['net'] for s in SYMBOLS}})
    grouped = {}
    for period in ('前16','後14','全30'):
        grouped[period] = {}
        for group in GROUPS:
            sessions = [r['セッション'] for r in classified if r['事後群'] == group and r['セッション'] in fixed[period]]
            grouped[period][group] = {'場数':len(sessions),'セッション':sessions,
                '商品別':{s:summarize(result['rows'],sessions,s) for s in SYMBOLS}}
        for symbol in SYMBOLS:
            for field, source in [('利益','profit'),('損失','loss'),('収支','net'),('取引組数','trades')]:
                assert sum(v['商品別'][symbol][field] for v in grouped[period].values()) == result['periods'][period][symbol][source]
    worst = {symbol:min(classified,key=lambda r:r['J2収支'][symbol]) for symbol in SYMBOLS}
    output = {'対象':'基準J2_F0_B0_H0_R0','用途':'終了後の相場方向による損益の説明だけ。手法選択・入口・途中・出口へ未使用。',
        '終値を見て手法を切り替えた':False,'新条件追加':False,'再選定':False,'新損益再生':False,
        'API取得':0,'実注文':0,'全30は既知資料':True,
        '分類定義':'保存candle_5minの当場最初のopenから最後のcloseへの価格差の符号。両商品正=双方上昇、両商品負=双方下落、符号が逆=逆方向、一方でも差0=同値含む。',
        '横ばい閾値':'設定しない。微小変動でも符号通りに分類。',
        '範囲限界':'始終符号はセッション中ずっと一方向だった意味ではない。途中の往復・反転を含む。最初と最後の保存足を使い、公式始値終値や執行期限の価格と同一とは限らない。',
        '群別会計':grouped,'全場の事後ラベル':classified,'商品別最悪場':worst,
        '利益損失の定義':'立会手数料後の全決済明細金額。商品間を円合算しない。無取引を勝ちに数えない。',
        '判断上の限界':'ある群で黒字でも、その群を開始時に知る能力や群を判別して切り替える戦略の収益性は示していない。',
        '出典SHA256':HASHES,'解析器SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = HERE/'evidence/相場方向別の事後診断.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'保存':str(target),'全30群別':grouped['全30']},ensure_ascii=False))


if __name__ == '__main__':
    main()
