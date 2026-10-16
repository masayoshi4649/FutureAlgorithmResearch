"""43親の小射影だけから、原因と入口対照の勝ち反証を保存する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
SOURCE = HERE/'同母二商品43実親の原因射影.json'
EXPECTED = 'e8451fd00380d04199072443f4f6c04e6561de039bad20e6b698a59a8279da73'
VALUE = {'TOPIX': 1000., 'NK225': 10.}


def witness(row: dict) -> dict:
    """
    機能: 完成小射影の当時入口と保存損益だけを短く射影する。
    引数: row(dict)は保存した実親。
    返り値: dictは資格対照用の原行と勝敗。新政策の取引ではない。
    """
    return dict(session=row['session'], symbol=row['symbol'], parent=row['paper_parent'],
        公開=row['公開'], side=row['side'], 実q=row['実初回q'], 票数=row['初回方向票数'],
        balance=row['候補方向釣合い'], 元実収支=row['実親']['収支'],
        元事後清算ピーク=row['実親清算経路']['事後の最大清算利益'])


def run() -> None:
    """
    機能: 根指定のbalance二対照と執行差・勝敗尺度を小資料だけで集計する。
    引数: なし。
    返り値: None。元金融の親削除を新金融収支と呼ばない。
    """
    saved = SOURCE.read_bytes(); assert hashlib.sha256(saved).hexdigest() == EXPECTED
    data = json.loads(saved); assert data['全合格'] and len(data['実親']) == 43
    comparison = {}
    for cutoff in (.5, .75):
        comparison[str(cutoff)] = {}
        for symbol in ('TOPIX', 'NK225'):
            rows = [r for r in data['実親'] if r['symbol'] == symbol]
            keep = [r for r in rows if r['候補方向釣合い'] >= cutoff]
            reject = [r for r in rows if r['候補方向釣合い'] < cutoff]
            comparison[str(cutoff)][symbol] = dict(
                元実親分母=len(rows), 資格残存元勝ち=sum(r['実親']['収支'] > 0 for r in keep),
                資格残存元負け=sum(r['実親']['収支'] < 0 for r in keep),
                資格拒否元勝ち=sum(r['実親']['収支'] > 0 for r in reject),
                資格拒否元負け=sum(r['実親']['収支'] < 0 for r in reject),
                残存元親=[witness(r) for r in keep], 拒否元親=[witness(r) for r in reject],
                残存票数分布=dict(Counter(r['初回方向票数'] for r in keep)))
    costs = {}; execution = {}; frequency = {}
    for symbol in ('TOPIX', 'NK225'):
        rows = [r for r in data['実親'] if r['symbol'] == symbol]
        costs[symbol] = {}
        for tag, win in (('元勝ち', True), ('元負け', False)):
            group = [r for r in rows if (r['実親']['収支'] > 0) == win]
            costs[symbol][tag] = dict(親数=len(group),
                実fillspread呼値分布=dict(Counter(r['実fillspread']/r['観測呼値'] for r in group)),
                公開からfillの不利呼値分布=dict(Counter(r['公開からfillの新規側不利移動呼値'] for r in group)),
                公開とfillが同価格時計=sum(r['新規']['price_time_s'] == r['公開']['price_time_s'] for r in group))
        execution[symbol] = []
        for row in rows:
            assert not row['部分返済あり'] and len(row['返済']) == 1
            e = row['返済'][0]; side = row['side']; qty = row['実初回q']
            decision_price = e['判断']['bid' if side == 1 else 'ask']
            decision_net = side*(decision_price-row['実新規価格'])*qty*VALUE[symbol]-row['実往復料']
            change = row['実親']['収支']-decision_net
            execution[symbol].append(dict(**witness(row), reason=e['理由'], 判断=e['判断'], 約定=e['約定'],
                返済判断時の当親費用後清算=decision_net, 次normal返済約定との差=change))
        all_group = data['集計'][symbol]['全親']; win_group = data['集計'][symbol]['勝親']; loss_group = data['集計'][symbol]['負親']
        mean_win = win_group['収支']/win_group['親数']; mean_loss = -loss_group['収支']/loss_group['親数']
        frequency[symbol] = dict(元親勝率=all_group['勝ち']/all_group['親数'], 平均利益円=mean_win,
            平均損失円=mean_loss, 平均勝敗金額比=mean_win/mean_loss,
            保存平均額に対する収支ゼロ必要勝率=mean_loss/(mean_loss+mean_win),
            保存元金額利益割合=win_group['収支']/(win_group['収支']-loss_group['収支']),
            注意='勝敗額を固定した算術尺度。将来勝率や新条件の黒字保証ではない。')
    output = dict(全合格=True, 元小射影SHA256=EXPECTED,
        source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        根指定の入口釣合い対照=comparison, 費用と約定分布=costs, 返済判断と次normal約定差=execution,
        勝敗頻度と収支必要頻度=frequency,
        比率の論理='balance=(候補方向票−逆票)/全方向票。0.5は候補票が逆票の3倍以上、0.75は7倍以上。1更新1票で数量強度でも独立試行数でもない。',
        対照留保=['0.5/0.75は根が原因観測後に指定した二対照。未見データの検証ではない。',
            '完成元金融43親の入口資格だけを分類。全feedへの門適用・q0・取消・busy・再参加を再計算しないので新収支を算出しない。',
            '新母数は元実親43より増減し得る。元敗親の拒否件数を避けた実損失へ置換しない。',
            '方向票は過去60秒の出来高正増/Last対直前BBOの代理。真の攻撃注文、持続性、取引主体の焦りを証明しない。'],
        大型入力追加読取=0, 台帳追加読取=0, 原板=0, NPZ=0, API=0, 金融=0, 公開変更=0)
    target = HERE/'入口釣合い二対照と執行差の小検算.json'; assert not target.exists()
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')
    print('43親の入口資格二対照と執行差を保存。新金融0。', flush=True)


if __name__ == '__main__':
    run()
