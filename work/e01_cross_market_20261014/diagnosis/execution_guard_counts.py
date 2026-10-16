"""43実親の小射影だけから、公開後の不利約定価格と気配幅拡大を数える。"""

import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
SOURCE = HERE/'同母二商品43実親の原因射影.json'
EXPECTED = 'e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'


def run() -> None:
    """
    機能: 同母43親の公開→最初の次正常気配悪化を、商品×元勝敗で数える。
    引数: なし。固定小射影だけを使う。
    返り値: None。新収支、親削除金融、packet又は台帳の追加読取を行わない。
    """
    saved = SOURCE.read_bytes(); assert hashlib.sha256(saved).hexdigest() == EXPECTED
    data = json.loads(saved); assert data['全合格'] and len(data['実親']) == 43
    rows = []
    for old in data['実親']:
        pub, fill, side = old['公開'], old['新規'], old['side']
        assert side in (-1, 1) and fill['raw_seq'] > pub['raw_seq']
        pub_price = pub['ask' if side == 1 else 'bid']; fill_price = fill['ask' if side == 1 else 'bid']
        assert fill_price == old['実新規価格']
        price = side*(fill_price-pub_price) > 0
        pub_spread = pub['ask']-pub['bid']; fill_spread = fill['ask']-fill['bid']
        widened = fill_spread > pub_spread
        rows.append(dict(session=old['session'], symbol=old['symbol'], paper_parent=old['paper_parent'],
            side=side, 元勝敗='勝ち' if old['実親']['収支'] > 0 else '負け' if old['実親']['収支'] < 0 else '零',
            元実収支=old['実親']['収支'], 公開=pub, 実新規=fill, 公開新規側価格=pub_price,
            実fill新規側価格=fill_price, 新規側不利価格変化=price,
            不利価格変化呼値=side*(fill_price-pub_price)/old['観測呼値'],
            公開気配幅=pub_spread, 実fill気配幅=fill_spread,
            気配幅拡大=widened, 両条件AND=price and widened, どちらかOR=price or widened))
    groups = {}
    for symbol in ('TOPIX', 'NK225'):
        groups[symbol] = {}
        for tag in ('勝ち', '負け', '全親'):
            own = [r for r in rows if r['symbol'] == symbol and (tag == '全親' or r['元勝敗'] == tag)]
            n = len(own); assert n > 0
            groups[symbol][tag] = dict(分母=n,
                counts={k: sum(r[k] for r in own) for k in ('新規側不利価格変化', '気配幅拡大', '両条件AND', 'どちらかOR')},
                rates={k: sum(r[k] for r in own)/n for k in ('新規側不利価格変化', '気配幅拡大', '両条件AND', 'どちらかOR')})
    target = HERE/'公開からD0新規への価格悪化と拡幅の43親小測定.json'; assert not target.exists()
    value = dict(全合格=True, 条件ID=data['条件ID'], 元小射影SHA256=EXPECTED,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 分母='TOP19/NK24の旧完結実親43。全paper公開候補ではない。',
        定義=dict(不利='買いは実fillask>公開ask、売りは実fillbid<公開bid。',
            拡幅='実fillask−実fillbid > 公開ask−公開bid。', OR='不利価格又は拡幅のどちらか。',
            時間='公開の後原seqにあるD0の最初の正常気配。価格時計が同じでも別原行。'),
        集計=groups, 実親=rows,
        後段仮説='公開時の買い上限ask/売り下限bidを持つ価格制限と、発注前の新鮮な気配幅審査。旧失敗だけでなく旧回復勝ちも見送りになる可能性を検証する。',
        留保=['元実親に対する当時価格差の記述で、新条件の約定/損益ではない。親を削除した金額合計を計算しない。',
            '公開後の気配を公開時に知ったことにはしない。価格制限注文なら不利側は未約定として予約/取消/後参加まで再生する必要がある。',
            '次正常気配の拡幅を見て同じ行の既存成行約定を取り消す模型は、実際の発注/取消と同じとは限らない。発注前審査と発注後の制限価格を区別する。',
            '幅の審査だけでは注文後の拡幅を保証できない。新規上限/下限、未約定寿命、取消先後を別途事前固定し、根が金融登録してから再生する。'],
        大型入力追加読取=0, 台帳追加読取=0, 原板=0, NPZ=0, API=0, 新金融=0, 公開変更=0)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(groups, ensure_ascii=False), flush=True)
    print('小測定SHA256 '+hashlib.sha256(target.read_bytes()).hexdigest(), flush=True)


if __name__ == '__main__':
    run()
