"""親を相殺しない金額利益割合に対する固定配分の上限を独立検証する。"""

import hashlib
import json
import math
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SYMBOLS = ('TOPIX', 'NK225')


def read(path):
    """
    機能: 凍結済み条件又は保存された会計と注文を読む。
    引数: path (Path)。
    返り値: object。原本や既存成果には書き込まない。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 使用資料の内容指紋を求める。
    引数: path (Path)。
    返り値: str の SHA256。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def load(ident):
    """
    機能: 旧30と事前選定後の追加1を結合し保存指紋を照合する。
    引数: ident (str)。
    返り値: tuple[dict,list[Path]] の全31台帳と使用資料。
    """
    answer = {}; paths=[]
    for base in (WORK, WORK/'extra'):
        result_path=base/'results'/f'{ident}.json'
        ledger_path=base/'ledgers'/f'{ident}.pkl'
        result, ledger=read(result_path), read(ledger_path)
        assert sha(ledger_path)==result['ledger_SHA256'] and not set(answer)&set(ledger)
        answer.update(ledger); paths.extend((result_path,ledger_path))
    assert len(answer)==62
    return answer,paths


def totals(values):
    """
    機能: 親別の費用後利益・損失を相殺せず算定する。
    引数: values (ndarray[float]) の親純損益。
    返り値: dict。金額変動なしは利益割合を未定義とする。
    """
    profit=float(values[values>0].sum()); loss=float(-values[values<0].sum())
    return dict(profit=profit,loss=loss,net=profit-loss,
                profit_share=profit/(profit+loss) if profit+loss else None,
                parents=len(values),wins=int((values>0).sum()),losses=int((values<0).sum()))


def same(a,b):
    """
    機能: 保存値を許容差なしで照合する。
    引数: a/b (ndarray)。
    返り値: None。
    """
    np.testing.assert_array_equal(a,b)


def fee_comparison(smaller, larger, factor, symbol):
    """
    機能: 同じ注文経路で数量だけを縮小した場合の手数料切捨て差を測定する。
    引数: smaller/larger (list[ndarray])、factor (float)、symbol (str)。
    返り値: dict。数量依存の約定量とスリッページはモデル外と明示する。
    """
    net_small=[]; net_large=[]; rebates=[]; orders=0
    fee_unit=41.8 if symbol=='TOPIX' else 11.
    for first,second in zip(smaller,larger):
        a,b=first['orders'],second['orders']
        columns=[i for i in range(17) if i not in (2,5,9,16)]
        same(a[:,columns],b[:,columns]); same(a[:,5],b[:,5]*factor)
        for row in a:
            assert row[9]==math.floor(row[5]*fee_unit+1e-8)
        rebates.extend((b[:,9]*factor-a[:,9]).tolist()); orders+=len(a)
        ta,tb=first['trades'],second['trades']
        same(ta[:,[i for i in range(16) if i not in (0,5,8,9,10,11)]],tb[:,[i for i in range(16) if i not in (0,5,8,9,10,11)]])
        same(ta[:,5],tb[:,5]*factor); same(ta[:,10],tb[:,10]*factor)
        net_small.extend(ta[:,11]); net_large.extend(tb[:,11]*factor)
    net_small,net_large=np.asarray(net_small),np.asarray(net_large)
    rebate=float(np.sum(rebates))
    assert np.allclose(net_small.sum()-net_large.sum(),rebate,rtol=0,atol=1e-6)
    assert ((net_small>0)==(net_large>0)).all() and ((net_small<0)==(net_large<0)).all()
    scaled=totals(net_large); actual=totals(net_small)
    return dict(同じ新規返済価格経路=True,注文数=orders,縮小倍率=factor,
                比例料金からの節約額=rebate,親の利益損失符号反転=0,
                比例会計の利益割合=scaled['profit_share'],切捨て実会計の利益割合=actual['profit_share'],
                割合差パーセントポイント=(actual['profit_share']-scaled['profit_share'])*100,
                手数料切捨ては量による微差であり分散効果ではない=True)


def main():
    """
    機能: 全31の固定8対2非干渉と利益割合上限・切捨て例外を監査する。
    引数: なし。
    返り値: None。review 内の新規 JSON だけを保存する。
    """
    fixed=read(WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items(): assert sha(ROOT/relative)==digest,relative
    full_proof=read(WORK/'audit/全38条件全31場の仮説と最初返済及び全原板清算会計の独立検算.json')
    assert full_proof['全合格'] and full_proof['検査件数']['全口座']==2356
    for relative,digest in full_proof['SHA256'].items(): assert sha(ROOT/relative)==digest,relative
    analysis=read(WORK/'analysis/比較結果.json')
    records={}; paths=[Path(__file__),WORK/'事前固定.json',WORK/'analysis/比較結果.json',
                       WORK/'audit/全38条件全31場の仮説と最初返済及び全原板清算会計の独立検算.json']
    for ident in ('J10','J8','O10','O2','M82'):
        records[ident],used=load(ident); paths.extend(used)
    columns=[i for i in range(17) if i not in (2,16)]
    trade_columns=list(range(1,16)); event_columns=[i for i in range(12) if i!=1]
    counts=dict(源別口座=0,源別注文=0,源別親=0,源別全行時価指紋=0,源別予約管理イベント=0)
    conclusions={}; fee_proof={}
    for symbol in SYMBOLS:
        sessions=fixed['全31']
        source_totals=[]
        for source,ident in ((0,'J8'),(1,'O2')):
            values=[]
            for session in sessions:
                mixture=records['M82'][session,symbol]; single=records[ident][session,symbol]
                orders=mixture['orders'][mixture['orders'][:,3]==source]
                same(orders[:,columns],single['orders'][:,columns])
                trades=mixture['trades'][mixture['trades'][:,1]==source]
                same(trades[:,trade_columns],single['trades'][:,trade_columns])
                events=mixture['events'][mixture['events'][:,2]==source]
                own=single['events'][single['events'][:,2]==source]
                same(events[:,event_columns],own[:,event_columns])
                assert mixture['source_curve_column_SHA256'][source]==single['source_curve_column_SHA256'][source]
                values.extend(trades[:,11]); counts['源別口座']+=1
                counts['源別注文']+=len(orders); counts['源別親']+=len(trades)
                counts['源別予約管理イベント']+=len(events); counts['源別全行時価指紋']+=1
            result=totals(np.asarray(values)); source_totals.append(result)
            formal=analysis['results'][ident]['periods']['全31'][symbol]
            for name in ('profit','loss','net','profit_share'):
                assert result[name]==formal[name]
        profit=sum(row['profit'] for row in source_totals)
        loss=sum(row['loss'] for row in source_totals)
        share=profit/(profit+loss)
        weights=[(row['profit']+row['loss'])/(profit+loss) for row in source_totals]
        weighted=sum(weight*row['profit_share'] for weight,row in zip(weights,source_totals))
        assert math.isclose(share,weighted,abs_tol=1e-12)
        assert min(row['profit_share'] for row in source_totals)<=share<=max(row['profit_share'] for row in source_totals)
        formal=analysis['results']['M82']['periods']['全31'][symbol]
        assert formal['profit']==profit and formal['loss']==loss and formal['profit_share']==share
        conclusions[symbol]=dict(追従J8=source_totals[0],反発O2=source_totals[1],
            金額変動での重み=weights,固定配分M82=dict(profit=profit,loss=loss,net=profit-loss,profit_share=share),
            比率の数学的上限=max(row['profit_share'] for row in source_totals),
            割合は枚数8対2の算術平均ではない=True,
            日別黒字数=dict(J8=analysis['results']['J8']['periods']['全31'][symbol]['positive_sessions'],
                          M82=formal['positive_sessions']),
            最大下落=dict(J8=analysis['results']['J8']['periods']['全31'][symbol]['equity_drawdown'],M82=formal['equity_drawdown']),
            新規だけを間引く場合80パーセントに必要な最低条件=dict(
                基準='固定配分M82', saved_loss_minus_missed_profit_over_4_at_least=loss-profit/4,
                利益を全く逃さない時に必要な損失削減率=(loss-profit/4)/loss))
        fee_proof[symbol]={}
        for small,large,factor in (('J8','J10',.8),('O2','O10',.2)):
            fee_proof[symbol][f'{large}から{small}'] = fee_comparison(
                [records[small][session,symbol] for session in sessions],
                [records[large][session,symbol] for session in sessions],factor,symbol)
    artificial=dict(
        日別損益の例=dict(戦略A=[300,-100],戦略B=[-100,300],合計=[200,200],
                        親別総利益=600,親別総損失=200,親別金額利益割合=.75,
                        日別を親として相殺後に算定した見掛けの割合=1.,
                        解釈='全日黒字へ分散できても、親別の金額利益割合75%は75%のまま。'),
        切捨ての例=dict(商品='TOPIXmini',片道8枚=334,片道2枚=83,別注文合計=417,
                      片道10枚の一注文=418,解釈='同方向の合算注文で必ず料金が減る仕様ではない。'),
        人工汎用の符号反転例=dict(注記='TOPIXの実呼値に乗らない汎用会計例。今回実際の親では反転0件。',
                          仮の一枚往復粗利益=83.3,一枚純利益=83.3-2*41,
                          十枚純利益=10*83.3-2*418))
    answer=dict(全合格=True,親別金額定義を維持=True,現在API取得=0,実注文=0,旧変更=0,
        結論=[
            '今回の固定8対2は、両源の単独同枚数の注文・価格・料金・全行時価と全31場で一致した。配分を変えても注文経路が同じなら、源の得意不得意は混ざるだけである。',
            '親別の利益・損失を相殺しない定義では S=sum(G_i)/sum(G_i+L_i)=sum(w_i*S_i)、w_i=(G_i+L_i)/sum(G_i+L_i)。各源の実際の配分枚数での割合の最大を超えない。',
            '相関低下には日別収支の平準化という別の価値がある。利益割合の上限と分散低下を同じ改善と呼ばない。今回M82は同枚数J8より両商品で最大下落が増えた。',
            '切捨てのため枚数を変えると源の割合は完全な比例ではない。しかし実際の配分枚数・料金で計算した加重平均の上限は変わらない。今回の切捨て差はTOPIXの微差、日経は0で、80%を説明しない。',
            '80%へ向けては、少なくとも実際に参加した源のどれかが80%以上になるほど、参加・約定・保有・返済の経路を良くする必要がある。時計で停止する方式だけに限定されない。'],
        数式の適用限界=[
            '最大の比較対象は同じ商品・期間・実配分枚数・実料金・実注文経路の源である。フル枠の比率を数量比例だけで代用しない。',
            '共有枠・条件付き参加・注文相殺・利確再配置・数量で約定が変わる方式は、源の実損益経路を変える。元の単独経路の比率上限をそのまま適用しない。変更後の実源別G/Lなら同じ恒等式が成立する。',
            '日別や複数源の損益をまとめて勝敗を付け直すと評価単位が変わる。今回の親別80%達成へ置き換えない。',
            '反対玉の料金・気配差・取消競合・未返済含み損を消して改善を作らない。'],
        全31非干渉件数=counts,商品ごとの実証=conclusions,数量比例の切捨て例外=fee_proof,人工境界=artificial,
        次の最低限の証拠=[
            '発注判断より前に読める数値で、反発を期待する根拠の消失又は追従の失敗を定義する。二市場の共同方向、各気配の反復更新、補充の失敗、基準からの逸脱等を別証拠として比較し、欠測を反対証拠へ置き換えない。',
            '元の損失を避けた額と元の利益を逃した額に加え、約定・再参加・共有枠で生まれた新しい全親のG/Lを別々に計算する。新規だけの間引きなら G-missed>=4*(L-saved) を満たす必要がある。',
            '共有枠は予約時から上限を占有し、同じ板で先に指値が成立した場合は取消で過去約定を消さない。枠を取られた源の逃した利益も比較する。',
            '入口での判別の追加価値と、保有中の損失抑制・利益保持・再参加の追加価値を分離して反証する。固定保有時間の採否を根拠なく結論にしない。',
            '条件固定→未来切断と毒入れ→全場会計→源別/場別損失の独立検算の順を維持する。既知31場での改修は再探索と明記し、新しい未閲覧場が追加されたら固定後に一度確認する。'],
        SHA256={str(path.relative_to(ROOT)):sha(path) for path in sorted(set(paths))})
    output=HERE/'固定配分の親別金額利益割合の上限と適用限界.json'
    assert output.resolve().is_relative_to(HERE.resolve()) and not output.exists()
    output.write_text(json.dumps(answer,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('全31の固定配分非干渉・加重平均上限・数量切捨て例外の独立監査合格。',flush=True)


if __name__=='__main__':
    main()
