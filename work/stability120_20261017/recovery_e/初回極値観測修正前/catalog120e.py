"""カバー維持二運用と上下対称の玉別利益回転を、三幅と二追尾で固定する。"""

from catalog120 import settings


def specifications() -> list[dict]:
    """
    機能: KEEP・RESCUE・ROTATEの十八条件を金融結果を見る前に列挙する。
    引数: なし。
    返り値: list[dict]はmode0/1/2・三幅・二追尾の固定仕様。
    """
    modes=(
        (0,'KEEP','勝ちカバーを組回収まで維持','最初の一枚後はLast極値から両方向へ段階追加。勝ち玉を個別に外さず、全玉・全費用込みの組純益を追尾して全返済する。両側上限のロックもそのまま測る。'),
        (1,'RESCUE','飽和時だけ逆側一枚を整理','組回収型を維持し、両側上限でLastが三単位反発したら売りの最悪負け玉、三単位反落したら買いの最悪負け玉を一枚返済する。その実損は同じ組に残す。'),
        (2,'ROTATE','上下対称に玉別の利益を回転','段階買い・段階売りを行い、純益peakが正になった玉は追尾幅戻りかつ純益が正なら一枚ずつ返済する。組全体追尾と飽和削減は使わず、空き枠を再利用する。'),
    )
    result=[]
    for mode,tag,name,description in modes:
        for width,fraction in enumerate((.000125,.00025,.0005),1):
            for trail in (1.,3.):
                result.append(dict(id=f'{tag}_S{width}_T{int(trail)}',mode=mode,name=name,
                    description=description,fraction=fraction,width_id=width,trail=trail,activation=0. if mode==2 else trail+1.,
                    rules=dict(入口='最初は一枚だけ予約し、実約定後は空き枠の動くLast安値＋3/4/5…単位で買い、高値−同幅で売り。極値は全正常Lastで更新し、発注判断と最初次気配の幅は一単位以内、価格は判断時の反対気配から観測一刻み以内。',
                        途中='個別返済後は当該空き枠を現在Lastへ戻し再利用する。途中の実現損益を含む全玉清算時価は常に記録する。' if mode==2 else '買い売り全玉の清算時価から初回予約時cashを引いて組純益を測る。勝玉の個別利確と方向別損切りは行わない。',
                        出口='玉別純益peak>0で追尾を開始し、最高純益から追尾幅戻りかつ現在純益正なら次正常原行で一枚返済。全flat完了行で極値を再準備し、再新規は翌原行から。場末も全返済。' if mode==2 else '組純益peakが追尾幅＋一単位へ進んだ後、追尾幅戻りかつ組純益正なら全返済予約。新規予約を取消し、全返済完了行で全極値を再準備し翌原行から再新規可。場末返済と約定悪化も計上。')))
    assert len(result)==18
    return result
