"""数量設計の保存診断から、失敗原因と未検証の次案を短くまとめる。"""
from pathlib import Path
import hashlib
import json
import numpy as np

HERE=Path(__file__).resolve().parent


def main():
    """
    機能: 固定十一条件の原因分解を読み、簡潔な日本語の証拠資料を保存する。
    引数: なし。
    返り値: None。売買再生・新しい条件選択は行わない。
    """
    path=HERE/'第四段階の数量効果と予算超過診断.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    records=[x for x in data['全親組'] if x['model']=='observed']
    metrics=[];lost=[];overshoot=[]
    for symbol in ('TOPIX','NK225'):
        groups={ident:{(x['session'],x['entry_seq'],x['direction']):x for x in records
                       if x['symbol']==symbol and x['id']==ident}
                for ident in ('A_GU','A_S2','A_J1_N','A_J1_R','A_D05_R','A_D05_Z','A_D10_R')}
        before,after=groups['A_S2'],groups['A_D05_R']
        assert before.keys()==after.keys()
        changes=[(after[k]['net']-before[k]['net'],k) for k in before]
        metrics.append(dict(symbol=symbol,同一入口数=len(before),
            改善組数=sum(d>0 for d,k in changes),改善額=sum(max(d,0.) for d,k in changes),
            悪化組数=sum(d<0 for d,k in changes),悪化額=-sum(min(d,0.) for d,k in changes),
            元黒字から赤字になった組数=sum(before[k]['net']>0 and after[k]['net']<0 for d,k in changes)))
        for delta,key in sorted(changes)[:2]:
            lost.append(dict(symbol=symbol,収支差=delta,
                追加なし={k:before[key][k] for k in ('session','direction','entry_jst','exit_jst','net','exit_reasons')},
                段階追加={k:after[key][k] for k in ('session','direction','entry_jst','exit_jst','net','initial_legs','additional_legs','exit_reasons')}))
        examples=sorted((x for x in after.values() if x['add_count'] and x['budget_exceeded']),
                        key=lambda x:x['budget_excess'],reverse=True)
        overshoot.append(dict(symbol=symbol,件数=len(examples),代表=examples[0] if examples else None))
    floors=[]
    for ident in ('A_J1_R','A_J1_Z','A_D05_R','A_D05_Z','A_D10_R'):
        for symbol in ('TOPIX','NK225'):
            groups=[x for x in records if x['id']==ident and x['symbol']==symbol]
            values=[a['remaining_retrace_atr'] for x in groups for a in x['additions']
                    if a['remaining_retrace_atr'] is not None]
            exits=[x for x in groups if 76 in x['exit_reasons']]
            floors.append(dict(id=ident,symbol=symbol,追加回数=len(values),
                追加約定値から新床までの戻り余地ATR中央値=float(np.median(values)),
                床全返済組数=len(exits),床全返済組収支=sum(x['net'] for x in exits)))
    out=dict(結論=[
        '少枚数化は損失金額を縮めるが、金額利益割合を上げなかった。追加なしの入口136/142組は元GUと同じ。',
        '主案の0.5ATR段階追加＋初回予算床はTOPIXで料金前から赤字。追加玉の収支悪化だけでなく、先に利益を持っていた初回玉まで全返済することで利益を減らした。',
        '同じ初回2/4枚の追加なしからの変化は、TOPIXでは初回玉−144,554円と追加玉−241,220円、日経では初回玉−44,700円と追加玉+2,072円。入口変更の差はない。',
        '一度に上限へ追加する初回予算床は、追加後に戻れる幅が中央値でTOPIX0.283ATR・日経0.275ATR。元の広いトレールより先に、この狭い床が返済を決めた。',
        '段階追加の床通過は各8組。全件、公開済み床の価格なら初回予算内だが観測現在値が床を通過した。指定価格モデルでは追加後の超過は0組。これは価格線を損失額の保証と扱えない問題であり、未公開の床を遡って使う順序違反は見つからない。',
        'より遅い1ATR段階追加は主案より改善したが、全30場では両商品とも同初回枚数・追加なしの収支を下回り、共通する新しい改善解にはならなかった。'],
        新床なしの意味='A_J1_Nには元GUの実組1ATR損失予算による次行返済が残る。初回玉に対してTOP40組・日経35組で実際に発動した。新しい0.75ATR/0円の価格床だけを加えない対照であり、無制限保有ではない。',
        期間制約='全30場は既知データ。事後の経路・極値・価格差は原因説明のみに使用し、取引条件や候補選びへ戻していない。',
        未検証の次案=[
            '初回玉と追加玉の返済を分離し、追加失敗の返済で初回玉の広い出口を強制終了しない比較。ただし親組全体の初回予算を厳守する設計とは両立条件の再検討が必要。今回の結果で有効と証明された案ではない。',
            '順行到達だけを追加の根拠とする限り、追加玉は最初の玉より不利な原価で同じ反転を負担する。枚数や床幅の微調整を続ける前に、追加時点から先の期待損益が費用後で改善する独立根拠が必要。'],
        主案の同入口変化=metrics,早期全返済で失った具体例=lost,
        主案の床通過=overshoot,追加直後の戻り余地=floors,
        参照資料=str(path),参照SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
    target=HERE/'第四段階の短い原因結論.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(target)


if __name__=='__main__':main()
