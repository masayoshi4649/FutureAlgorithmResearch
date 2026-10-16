"""全18表示条件の安定性を、保存会計だけで条件別・商品別に短く整理する。"""

from pathlib import Path
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
PHASE=HERE.parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(PHASE))
import common


def share(rows: list[dict]) -> float | None:
    """
    機能: 親の利益/損失を相殺せず、金額利益割合を算出する。
    引数: rows(list[dict])は同商品セッション会計。
    返り値: float | Noneは総利益/(総利益+総損失)。無取引を勝ちにしない。
    """
    gain=sum(r['profit'] for r in rows);loss=sum(r['loss'] for r in rows)
    return gain/(gain+loss) if gain+loss else None


def main() -> None:
    """
    機能: 中央値/上位3黒字場除外/活動/金額割合/方向別を全18から保存する。
    引数: なし。金融結果の小JSONだけを読む。
    返り値: None。元台帳/cache/金融/原板/APIの再生や読取は行わない。
    """
    source=PHASE/'finance/results.json';result=common.read(source)
    assert result['全合格'] and result['account_count']==792 and result['display_account_count']==1188
    values={}
    for config in result['configs']:
        ident=config['id'];values[ident]={}
        for symbol in ('TOPIX','NK225'):
            rows=[r for r in result['cases'][ident]['rows'] if r['symbol']==symbol];assert len(rows)==33
            total=result['cases'][ident]['summary'][symbol]
            positive=sorted((r for r in rows if r['net']>0),key=lambda r:(-r['net'],r['session']))[:3]
            removed={r['session'] for r in positive};remaining=[r for r in rows if r['session'] not in removed]
            active=[r['net'] for r in rows if r['campaigns']>0]
            assert abs(sum(r['net'] for r in rows)-total['net'])<1e-4
            values[ident][symbol]=dict(quantity=config['quantity'][symbol],derived=config['local_policy']=='ALIGNED',
                利益=total['profit'],損失=total['loss'],収支=total['net'],金額利益割合=total['profit_share'],
                黒字場=total['positive_sessions'],赤字場=total['losing_sessions'],無取引場=total['no_trade_sessions'],活動場=total['active_sessions'],全場数=33,
                全場収支中央値=float(np.median([r['net'] for r in rows])),活動場収支中央値=float(np.median(active)) if active else None,
                上位3黒字場除外=dict(除外=[dict(session=r['session'],net=r['net']) for r in positive],
                    収支=sum(r['net'] for r in remaining),利益=sum(r['profit'] for r in remaining),損失=sum(r['loss'] for r in remaining),
                    金額利益割合=share(remaining)),
                決済親=dict(勝ち=total['winning_campaigns'],負け=total['losing_campaigns'],全親=total['campaigns']),
                平均利益=total['average_win'],平均損失=total['average_loss'],平均利益対平均損失=total['payoff'],
                買売別=total['directions'],源別=total['sources'],最悪場=total['worst_session'],
                基準との差=result['diagnosis'][ident][symbol])
    target=HERE/'全18の中央値と上位3除外及び活動と金額割合.json'
    common.write(target,dict(全合格=True,表示条件数=18,新金融条件数=12,派生条件数=6,対象場数=33,results=values,
        金額利益8割達成=[i for i,s in values.items() if all(s[p]['金額利益割合'] is not None and s[p]['金額利益割合']>=.8 for p in ('TOPIX','NK225'))],
        両商品上位3除外黒字=[i for i,s in values.items() if all(s[p]['上位3黒字場除外']['収支']>0 for p in ('TOPIX','NK225'))],
        新金融再生=0,入力cache読取=0,台帳読取=0,原板読取=0,API取得=0,
        定義=['上位3除外は商品別のnet最大の正の3セッション。暦日単位除外とは区別。',
            '利益/損失は費用後親netの正/負額。無取引場を黒字場/決済勝ちへ加えない。',
            'ALIGNED6は同じ既知C_ONLY半量経済の再利用。6つの独立成功としない。'],
        SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in (Path(__file__),source)}))
    print('全18の安定性を小JSONへ保存、金融再生0',flush=True)


if __name__=='__main__':main()
