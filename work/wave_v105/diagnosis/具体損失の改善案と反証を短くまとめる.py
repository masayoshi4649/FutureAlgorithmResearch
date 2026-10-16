"""完成した診断JSONだけから、当時の兆候と改善の代償を簡潔に整理する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    """
    機能: 新しい小診断と説明sourceの内容指紋を求める。
    引数: path(Path)は小ファイル。
    返り値: strはSHA256。旧入力を再読しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 実損失の内訳、支持線の突破gap、代表時刻と見送りの実黒字代償を保存する。
    引数: なし。
    返り値: None。新金融や新ラベル閾値を探索しない。
    """
    source = HERE/'赤字上位場の具体板と当時兆候及び反証.json'
    result = json.loads(source.read_text(encoding='utf-8'))
    assert result['全合格'] and len(result['全親']) == 90
    breakdown, references = {}, []
    for key in result['要約']:
        ident, symbol = key.split('|')
        rows = [row for row in result['全親'] if row['case'] == ident and row['symbol'] == symbol and row['net'] < 0]
        fee = sum(row['fees'] for row in rows)
        spread = sum(row['正確な現金分解']['入口spread費用円'] for row in rows)
        adverse = sum(row['正確な現金分解']['純価格逆行部分円'] for row in rows)
        positive = sum(row['正確な現金分解']['価格改善部分円'] for row in rows)
        loss = -sum(row['net'] for row in rows)
        assert abs(fee+spread+adverse-positive-loss) < 1e-5
        tick = .5 if symbol == 'TOPIX' else 10.
        multiplier = 1000 if symbol == 'TOPIX' else 10
        gaps = []
        for row in rows:
            quote = row['時点']['返済判断']['自己snapshot']['bid' if row['side'] == 1 else 'ask']
            stop = row['保有後にだけ判明']['最終停止線']
            gap = max(0., row['side']*(stop-quote))
            if gap > 1e-8:
                gaps.append(dict(session=row['session'], parent=row['parent'], 判断時刻=row['時点']['返済判断']['価格代理時刻'],
                    判断raw_seq=row['時点']['返済判断']['raw_seq'], 停止線=stop, 既に観測した清算quote=quote,
                    支持破れ時の線越え呼値=gap/tick, 線越え価格分円=gap*row['quantity']*multiplier,
                    次quotefill不利変化円=row['正確な現金分解']['返済判断からfillへの不利変化円']))
        breakdown[key] = dict(損失親=len(rows), 総損失=loss, 両側料金=fee, 入口spread=spread,
            純価格逆行=adverse, 価格改善の相殺分=positive,
            返済判断時に既に線を越えた親=len(gaps), その線越え量円=sum(value['線越え価格分円'] for value in gaps),
            明細=gaps, 式='総損失=両側料金+入口spread+純価格逆行−価格改善の相殺分。線越えやfill遅れは価格逆行の内数。')
    target_examples = [
        ('C_N30_B4', 'TOPIX', '2026-10-06_Day', 1),
        ('C_N30_B4', 'NK225', '2026-10-02_Day', 2),
        ('U_P10_T2', 'TOPIX', '2026-09-28_Day', 3),
        ('U_P10_T2', 'NK225', '2026-10-01_Day', 5)]
    explanations = [
        dict(当時見えた兆候='08:58:12の直前30秒は総移動15呼値に対して純上昇2呼値、14回反転。直前10秒は買い方向代理98・売り方向代理34でも、支持4172.5のbid表示量は7枚、同価格増加3・減少4。直近だけ強くても往復する価格帯の上側へ入っている。',
            失敗='4173.5で買い、08:59:01まで最大3呼値の順行。その利益を広い追尾で守れず、08:59:54にbid4170が停止4170.5を既に越えたため返済。判断後のfill悪化ではない。',
            改善案='入口前の価格往復を別の資格にする対照が優先。少し順行した後は、広い追尾とは別に小さい利益保険を比較する。',
            反証='09:00:20にbid4175.5へ回復したのは事後だけの事実。120秒内には元建値から12呼値逆行もあり、停止を広げれば安全に取れたとは言えない。'),
        dict(当時見えた兆候='09:32:51の直前30秒は総移動28呼値に対し純上昇1呼値、34回反転。売り方向代理24対買い12でも売りに値が進んでいない。支持68700のaskは35枚、同価格増加76・減少55。補充代理があっても価格の往復を止めていない。',
            失敗='68680で売り、09:34:02に最大6呼値順行したが広い追尾は利益を固定しない。09:35:46にask68740で支持境界返済、−622円。',
            改善案='価格が進まない出来高方向代理を信用し過ぎない。往復を除く入口対照と、一定順行後の利益保険を切り分ける。',
            反証='退出後120秒でも元建値を費用込みで回収する気配には戻っていない。保有延長だけで直る例ではない。'),
        dict(当時見えた兆候='09:57:38直前10秒はmid純移動0、買い方向代理15に売り0。支持4128のbid表示量は34枚で、増加11・減少5。ただし買い活動があっても価格は止まっている。直前赤字親と同方向で、同じ±2呼値帯へ再参加。',
            失敗='4129.5で買い。入口判断4129からfillへ0.5pt悪化。最大順行1呼値で利益追尾は発動せず、09:59:41に4127で返済、−2582円。相手日経も入口時66510/66520から返済時66450/66460へ下がっていた。',
            改善案='損失後の同方向・同価格帯の再参加を、新しい価格進行が起きるまで再準備させる単独対照。',
            反証='対象Uの同価格再参加ラベル6親はすべて赤字だったが、赤字上位場を選んだ範囲での事実。全33場の元黒字や後続状態を調べるまで安全な改善とは扱わない。'),
        dict(当時見えた兆候='11:07:03直前10秒は下向き1.5呼値で、売り方向代理11対買い1。しかし30秒では総移動19.5呼値に対して下向き0.5呼値、17回反転。二市場の短期方向一致は、長い同価格往復からの離脱を保証していない。',
            失敗='68460で売り、初回ask68480で既に2呼値のspread負担。11:07:27まで最大順行1呼値だったが、利益追尾を発動する3呼値には届かない。11:11:44のask68530で−722円。',
            改善案='10秒の一方向進行と、30秒の往復から離れたかを別々に要求する入口対照。',
            反証='同じ往復述語でUの実黒字もTOPIX6508円、日経1324円を見送る。条件を厳しくしただけで全日安定になる証拠ではない。')]
    for key, explanation in zip(target_examples, explanations, strict=True):
        ident, symbol, session, pid = key
        row = next(value for value in result['全親'] if value['case'] == ident and value['symbol'] == symbol and value['session'] == session and value['parent'] == pid)
        references.append(dict(case=ident, symbol=symbol, session=session, parent=pid, net=row['net'],
            元時点rawseq={name: value['raw_seq'] for name, value in row['時点'].items()}, **explanation))
    saved = dict(全合格=True, scope='完成済み90親診断の算数と4代表箇所だけ。新たな入力読取や金融再生なし。',
        診断SHA256=digest(source), sourceSHA256=digest(Path(__file__)), 損失の正確な分解=breakdown, 具体箇所=references,
        結論='主因は入口の往復帯への参加と、順行が小さい段階での逆行。次quote遅れだけを直しても大部分は消えない。Cで利益を返した例と、Uで利益保険が発動しなかった例を分ける。',
        次の優先対照=['入口の方向付き純進行と往復量の分離', '損失後の同方向近価格帯への再準備',
            '途中の支持喪失と相手市場逆行を出口に使う仮説', '利益保険と初期損切り・広い利益追尾を別部品として比較'],
        重要な反証='Cの選定赤字上位場には黒字親が一件もなく、この範囲で見送る利益0は当然。全33場のC黒字対照がまだ必要。退出後回復は、実際に元黒字を見送る代償とは別であり、幅拡大の利益ではない。',
        数量解釈='同価格表示量増減を約定や真の補充と断定しない。十段外は不明、出来高方向は最終価格の代理。',
        初回説明の訂正='日経1枚T2は往復料金22円/(倍率10円×呼値10)を呼値へ切り上げて1呼値、追尾2呼値を足した3呼値で発動。初回の文章4呼値は誤りで旧版を保持、会計数値・取引・入力は不変。',
        新入力読取=0, 原本読取=0, NPZ再読=0, 金融再生=0, counterfactual注文生成=0, API取得=0)
    target = HERE/'具体的に負けた板と改善の代償.json'
    assert not target.exists()
    target.write_text(json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print('4具体箇所と損失内訳・改善反証を保存。元入力再読0。')


if __name__ == '__main__':
    main()
