"""逆板維持の純述語を、独立逐次oracleと人工の当時接頭で確認する。"""

from copy import deepcopy
from pathlib import Path
import json
import sys

import numpy as np

from absorption_oracle import fixture, oracle, static_scope
from range_engine_check import digest, load


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_absorption_gate'


def variants(side: int) -> list[tuple[str,dict,int]]:
    """
    機能: 一瞬の数量減少・支持順行・価格変更・欠測・古いLastを反例として作る。
    引数: side(int)は買い又は売り。
    返り値: list[tuple[str,dict,int]]は人工名・原列・公開終点。正式資料は使わない。
    """
    base = fixture(side); opposing = 'ask' if side>0 else 'bid'; qty = opposing+'_qty'; supporting = 'bid' if side>0 else 'ask'
    names = ('基準','二接触','活動量だけ少ない','活動量初期量と等値','一票大量','活動量合計overflow','活動量比overflow','数量一瞬減少','数量微減少','数量増加','初期数量だけ大','支持一瞬順行','支持逆行',
        '逆価格変更後復帰','公開当行だけ新価格','尾部外数量欠測','尾部内数量欠測','別価格外側数量欠測',
        '尾部支持価格欠測','尾部spread不正','境界逆価格欠測','候補逆価格欠測',
        'e隣接資格だけ不明','尾部内隣接資格不明','旧Last出来高増加なし','一接触だけ','Last内側',
        '窓内出来高reset','窓内連番断裂','窓内価格時計逆行','票方向に同期しないLast',
        '窓境界以前の二接触','eの接触は除外','数量正数でも資格false','数量0でも資格true')
    result = []
    for name in names:
        a = deepcopy(base)
        if name=='二接触': a['volume_delta'][8]=0; a['volume_delta'][7]=6; a['volume_delta'][11]=6
        if name=='活動量だけ少ない': a['volume_delta'][[7,8,11]]=1
        if name=='活動量初期量と等値': a['volume_delta'][7]=3; a['volume_delta'][8]=3; a['volume_delta'][11]=4
        if name=='一票大量': a['volume_delta'][[7,8]]=0; a['volume_delta'][11]=10000
        if name=='活動量合計overflow': a['volume_delta'][[7,8,11]]=1e308
        if name=='活動量比overflow': a[qty][:]=np.nextafter(0.,1.)
        if name=='数量一瞬減少': a[qty][8]=9
        if name=='数量微減少': a[qty][8]=np.nextafter(10.,0.)
        if name=='数量増加': a[qty][8:]=20
        if name=='初期数量だけ大': a[qty][5]=20
        if name=='支持一瞬順行': a[supporting][8]+=side*.5
        if name=='支持逆行': a[supporting][8]-=side*.5
        if name=='逆価格変更後復帰': a[opposing][9]+=side
        if name=='公開当行だけ新価格': a[opposing][11]+=side
        if name=='尾部外数量欠測': a[qty][4]=np.nan; a['best_quantity_valid'][4]=False; a['price_transition_valid'][5]=False
        if name=='尾部内数量欠測': a[qty][8]=np.nan; a['best_quantity_valid'][8]=False; a['price_row_valid'][8]=False
        if name=='別価格外側数量欠測': a[opposing][9]+=side; a[qty][9]=np.nan; a['best_quantity_valid'][9]=False; a['price_row_valid'][9]=False; a['price_transition_valid'][10]=False
        if name=='尾部支持価格欠測': a[supporting][8]=np.nan
        if name=='尾部spread不正': a[supporting][8]=a[opposing][8]
        if name=='境界逆価格欠測': a[opposing][9]=np.nan
        if name=='候補逆価格欠測': a[opposing][11]=np.nan
        if name=='e隣接資格だけ不明': a['price_transition_valid'][5]=False
        if name=='尾部内隣接資格不明': a['price_transition_valid'][8]=False
        if name=='旧Last出来高増加なし': a['volume_delta'][7:]=0
        if name=='一接触だけ': a['volume_delta'][8:]=0
        if name=='Last内側': a['last'][7]=100.5
        if name=='窓内出来高reset': a['volume_delta_usable'][9]=False; a['volume_reset_reason'][9]=32
        if name=='窓内連番断裂': a['raw_seq'][9:]+=1
        if name=='窓内価格時計逆行': a['price_time_s'][8]=29
        if name=='票方向に同期しないLast': a['last'][7:9]=100. if side>0 else 101.
        if name=='窓境界以前の二接触': a['volume_delta'][:]=0; a['volume_delta'][3:5]=1; a['last'][3:5]=a[opposing][3:5]
        if name=='eの接触は除外': a['volume_delta'][:]=0; a['volume_delta'][5:7]=1; a['last'][5:7]=a[opposing][5:7]
        if name=='数量正数でも資格false': a['best_quantity_valid'][8]=False
        if name=='数量0でも資格true': a[qty][8]=0
        result.append((name,a,11))
    return result


def compare(F: object, V: object, raw: dict, row: int, side: int) -> tuple[dict,int]:
    """
    機能: 同じ当時票を使い、対象純述語と独立逐次oracleを比較する。
    引数: F/V(module)、raw(dict)、row/side(int)は検査sourceと人工。
    返り値: tuple[dict,int]は対象の測定結果と検査件数。
    """
    ctx = V.context(raw); base = V.measure(raw,ctx,row,60,side); got = F.measure(raw,ctx,row,side,base)
    eligible = bool(base['known'] and base['direction_votes']>=2)
    assert got['eligible']==eligible; count = 1
    if not eligible:
        if not base['known']: assert not got['known'] and got['hit'] is None
        else: assert got['known'] and not got['hit']
        return got,count+2
    expected = oracle(raw,ctx['direction'],base,side)
    assert got['known']==expected['known']; count += 1
    if not expected['known']:
        assert got['hit'] is None; return got,count+1
    fields = {'episode_start_raw_row':'start','candidate_raw_row':'end','opposite_price':'opposite_price',
        'initial_quantity':'initial_quantity','minimum_quantity':'minimum_quantity',
        'maximum_support_advance':'supporting_advance','touch_rows':'touch_rows','touch_count':'touch_count','hit':'matched',
        'touch_activity_volume':'activity_volume','touch_activity_to_initial_ratio':'activity_ratio'}
    for actual,gold in fields.items(): assert got[actual]==expected[gold],(actual,got,expected); count += 1
    assert got['episode_start_raw_seq']==int(raw['raw_seq'][expected['start']]); count += 1
    assert got['touch_raw_seq']==[int(raw['raw_seq'][j]) for j in expected['touch_rows']]; count += 1
    return got,count


def main() -> None:
    """
    機能: 買売対称・欠測・一瞬の反例・未来同時計排除を結果前人工で独立確認する。
    引数: なし。金融結果・NPZ・E01保存cache・APIは読まない。
    返り値: Noneは所有領域の独立述語検査証跡。未知を成立へ変えない。
    """
    target = HERE/'absorption_同価格数量支持と当時接頭の独立人工.json'; assert not target.exists()
    before = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    C = load('吸収独立catalog',SOURCE/'catalog.py'); sys.modules['catalog']=C
    V = load('吸収独立votes',SOURCE/'votes.py'); F = load('吸収独立feature',SOURCE/'feature.py')
    assert digest(SOURCE/'votes.py')==digest(ROOT/'work/wave_v106/e01_trade_gate/votes.py')
    observations = []; results = {}; checks = 0
    for side in (1,-1):
        for name,raw,row in variants(side):
            got,n = compare(F,V,raw,row,side); checks += n
            results[name,side] = got
            observations.append(dict(人工名=name,方向=side,eligible=got['eligible'],known=got['known'],hit=got['hit'],reason=got['reason'],
                開始=got['episode_start_raw_row'],接触=got['touch_rows'],最小量=got['minimum_quantity'],支持進行=got['maximum_support_advance']))
            # ----------------------------------------
            # 終点の後は同価格時計の別原行でも未公表。未来票・数量・価格を変えても終点は不変。
            short = {k:v[:row+1].copy() for k,v in raw.items()}; prefix,nprefix = compare(F,V,short,row,side)
            assert prefix==got; checks += nprefix+1
            future = deepcopy(raw)
            future['bid'][row+1:]=10.; future['ask'][row+1:]=11.; future['last'][row+1:]=10.
            future['bid_qty'][row+1:]=0.; future['ask_qty'][row+1:]=np.nan; future['price_time_s'][row+1:]=-1.
            future['volume_delta'][row+1:]=100000.
            altered,nfuture = compare(F,V,future,row,side); assert altered==got; checks += nfuture+1
    for name in {name for name,_ in results}:
        a,b = results[name,1],results[name,-1]
        for field in ('eligible','known','hit','touch_rows','touch_count','minimum_quantity','initial_quantity','maximum_support_advance','touch_activity_volume','touch_activity_to_initial_ratio'):
            assert a[field]==b[field],(name,field,a,b); checks += 1
    # ----------------------------------------
    # flat・空入力・公開元行の不一致を、新しい方向や偽の境界へ補完しない。
    raw = fixture(); ctx = V.context(raw); base = V.measure(raw,ctx,11,60,1)
    for label,values in (('flat方向',dict(side=0,raw=raw,row=11,base=base)),
        ('空原行',dict(side=1,raw={k:v[:0] for k,v in raw.items()},row=0,base=base)),
        ('公開元seq違い',dict(side=1,raw=raw,row=11,base=dict(base,candidate_raw_seq=9999))),
        ('公開元時計違い',dict(side=1,raw=raw,row=11,base=dict(base,candidate_price_time_s=9999.)))):
        try:
            F.measure(values['raw'],ctx,values['row'],values['side'],values['base'])
        except AssertionError:
            checks += 1
        else:
            raise AssertionError(label+'を補完した')
    assert results['基準',1]['hit'] is True and results['二接触',1]['touch_count']==2
    for name in ('活動量だけ少ない','数量一瞬減少','数量微減少','支持一瞬順行','逆価格変更後復帰','公開当行だけ新価格','eの接触は除外'):
        assert results[name,1]['known'] and results[name,1]['hit'] is False; checks += 1
    for name in ('尾部外数量欠測','e隣接資格だけ不明'):
        assert results[name,1]['known'] and results[name,1]['hit'] is True; checks += 1
    for name in ('活動量合計overflow','活動量比overflow','尾部内数量欠測','尾部支持価格欠測','尾部spread不正','境界逆価格欠測','候補逆価格欠測','尾部内隣接資格不明'):
        assert not results[name,1]['known'] and results[name,1]['hit'] is None; checks += 1
    assert C.WINDOW==60 and C.MINIMUM_TOUCHES==2
    assert before=={p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    assert results['活動量初期量と等値',1]['hit'] is True and results['活動量初期量と等値',1]['touch_activity_to_initial_ratio']==1
    assert not results['一票大量',1]['eligible'] and results['一票大量',1]['hit'] is False
    proof = dict(全合格=True,範囲='新非金融述語を独立逐次oracleと買売反例、各接頭と未来改変で比較。正式入力及び結果は未読。',
        検査数=checks,人工数=len(observations),人工=observations,source_SHA256=before,source開始終端一致=True,
        レビューsource_SHA256=digest(Path(__file__)),独立oracleSHA256=digest(HERE/'absorption_oracle.py'),旧方式の限定静的確認=static_scope(),
        旧二更新だけの独立oracle保存='work/wave_v106/price_review/absorption_oracle_初回二更新案.py',
        旧oracleSHA256=digest(HERE/'absorption_oracle_初回二更新案.py'),
        金融=0,原板=0,NPZ=0,大型cache=0,API=0,
        留意点=['同価格の最良数量非減少と接触代理は、真の補充・注文主体・攻撃数量の同定ではない。',
            '支持価格が一瞬でも順行すれば、戻っても不成立。数量が一瞬でも減れば、回復しても不成立。',
            'eの外側数量資格とe自身の隣接資格を混ぜない。e以後の全当時行を使い、接触はe+1以後だけ。',
            '旧完全C/RのSupply門は数量一定では準備不可だが、省略対照や全過去方式の未試行は主張しない。',
            '同価格Lastの更新間総出来高差を、その価格に当たった真の量へ配賦しない。比1は十分な公表活動を求める静的門である。',
            '2更新のみの初回案に活動量/初期量>=1を追加した時点は大型入力/成績を見る前。金融結果から閾値を変更していない。',
            '実入力での成立件数や勝敗選別、金融差は、この人工からは未測定。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('逆板維持の独立人工合格',checks,len(observations),digest(target))


if __name__=='__main__': main()
