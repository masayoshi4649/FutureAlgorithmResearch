"""親別の金額割合上限と、同じ上限枚数での場収支平準化を区別する。"""

import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]


def read(path):
    """
    機能: 保存済みの検証結果だけを読む。
    引数: path (Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 使用資料の内容指紋を取得する。
    引数: path (Path)。
    返り値: str の SHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    """
    機能: 全31場の相関・分散恒等式・同枠対照・無取引場の寄与を独立確認する。
    引数: なし。
    返り値: None。既存成果を変更しない。
    """
    analysis_path=WORK/'analysis/比較結果.json'
    diagnostic_path=HERE/'固定配分の相関と場収支のぶれの診断.json'
    mathematics_path=HERE/'固定配分の親別金額利益割合の上限と適用限界.json'
    data,diagnostic,mathematics=read(analysis_path),read(diagnostic_path),read(mathematics_path)
    assert diagnostic['全合格'] and mathematics['全合格']
    assert sha(analysis_path)==diagnostic['会計SHA256']
    records={}
    for symbol in ('TOPIX','NK225'):
        sessions=data['sessions']
        arrays={ident:np.array([next(row['net'] for row in data['results'][ident]['rows']
                   if row['session']==session and row['symbol']==symbol) for session in sessions],float)
                for ident in ('J8','O2','M82','J10')}
        a,b,c=arrays['J8'],arrays['O2'],arrays['M82']
        np.testing.assert_array_equal(a+b,c)
        variances={ident:float(value.var(ddof=1)) for ident,value in arrays.items()}
        covariance=float(np.sum((a-a.mean())*(b-b.mean()))/(len(a)-1))
        assert np.isclose(variances['M82'],variances['J8']+variances['O2']+2*covariance,atol=1e-5)
        deviation={ident:float(value.std(ddof=1)) for ident,value in arrays.items()}
        correlation=float(covariance/(deviation['J8']*deviation['O2']))
        root=diagnostic['結果'][symbol]
        for field,actual in [('追従と反発の場収支相関',correlation),('追従の場収支標準偏差円',deviation['J8']),
                             ('反発の場収支標準偏差円',deviation['O2']),('併用の場収支標準偏差円',deviation['M82'])]:
            assert np.isclose(root[field],actual,atol=1e-9)
        counts=dict(追従赤字を合計黒字に=int(((a<0)&(c>0)).sum()),
                    追従黒字を合計赤字に=int(((a>0)&(c<0)).sum()),
                    追従0円を合計黒字に=int(((a==0)&(c>0)).sum()),
                    追従0円を合計赤字に=int(((a==0)&(c<0)).sum()))
        assert counts['追従赤字を合計黒字に']==root['反発が追従赤字を黒字化した場数']
        assert counts['追従黒字を合計赤字に']==root['反発が追従黒字を赤字化した場数']
        drawdowns={ident:data['results'][ident]['periods']['全31'][symbol]['equity_drawdown']
                   for ident in ('J8','O2','M82','J10')}
        records[symbol]=dict(場数=31,日別相関=correlation,標本標準偏差円=deviation,標準偏差の自由度調整=1,
            分散加法の恒等式一致=True,同量J8への追加で標準偏差が増加=deviation['M82']>deviation['J8'],
            同片方向上限J10から8対2への再配分で標準偏差が減少=deviation['M82']<deviation['J10'],
            原板全行最大下落円=drawdowns,同枠J10に対する下落差=drawdowns['M82']-drawdowns['J10'],
            場の勝敗変化=counts,親別金額利益割合=mathematics['商品ごとの実証'][symbol]['固定配分M82']['profit_share'])
    output=HERE/'固定配分の金額上限と日別分散低下を区別した独立補足.json'
    assert not output.exists()
    answer=dict(全合格=True,結果=records,
        結論=[
            '同じ片方向上限のJ10から8対2へ再配分すると、両商品の場収支の標準偏差は低下した。この平準化は固定配分の価値であり、配分が無意味だという結論ではない。',
            '同じJ8にO2を追加した比較では標準偏差も最大下落も増えた。8枠単独と10枠配分を、同じ資金・枚数の比較と混同しない。',
            '同枠J10との比較でもNK225の全原板最大下落は増えた。場単位のばらつきが小さいことと、期間途中に深く沈まないことは別である。',
            '平準化しても親を相殺しない金額利益割合の加重平均上限は維持される。今回の53.35%・51.98%を80%達成の改善とは呼べない。',
            'この31場での相関と分散は事後診断であり、将来の相関の安定性を証明しない。無取引を勝ちには数えていない。'],
        旧又は凍結変更=0,API取得=0,実注文=0,
        SHA256={str(path.relative_to(ROOT)):sha(path) for path in (Path(__file__),analysis_path,diagnostic_path,mathematics_path)})
    output.write_text(json.dumps(answer,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('同枠の平準化と金額割合上限を区別した独立補足に合格。',flush=True)


if __name__=='__main__':
    main()
