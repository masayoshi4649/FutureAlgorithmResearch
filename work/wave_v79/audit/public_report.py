"""公開HTMLの埋込み会計・時刻・事後描画を保存原本へ独立照合する。"""

from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

from full_accounts import HERE, study
from independent_account import save


def digest(path) -> str:
    """機能: 保存済みファイルのバイト列のSHA256を求める。

    引数: path(Path)。返り値: ハッシュ文字列(str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """機能: 公開資料への変換で数値・注文対応・前後関係が変わらないことを確認する。

    引数: なし。返り値: なし(None)。未確認の因果関係や到着順を証明する検査ではない。
    """
    work=HERE.parent
    out=work.parents[1]/'アルゴリズム調査/00075_J2赤字上位セッションの板検証と防止策'
    path=out/'赤字上位3セッションの板と防止策.html'
    html=path.read_text(encoding='utf8')
    payload=re.search(r'<script>const DATA=(.*?);</script>',html,re.S)
    assert payload is not None
    data=json.loads(payload.group(1))
    fixed=study.load(work/'事前固定.json')
    cases=study.load(work/'report/6ケース.json')
    effects=study.load(work/'analysis/全条件の効果.json')
    replays=study.load(work/'analysis/赤字上位6口座の再生時刻.json')
    results={c['id']:study.load(work/'results'/f'{c["id"]}.json') for c in fixed['条件']}
    assert data['cases']==cases['ケース']
    assert data['results']==results and data['effects']==effects and data['replay']==replays
    assert data['sessions']==fixed['全30'] and data['worst']==fixed['商品別赤字上位3']
    assert data['days']==fixed['開始日合計の赤字上位3']
    assert data['charts']==study.load(work/'report/描画資料.json')
    public=study.load(out/'公開会計.json')
    assert public['条件']==results and public['比較']==effects and public['赤字上位の板と注文']==cases
    assert public['全30']==data['sessions']
    expected=(work/'report/template.html').read_text(encoding='utf8')
    expected=expected.replace('__STYLE__',(work/'report/style.css').read_text(encoding='utf8'))
    expected=expected.replace('__SCRIPT__',(work/'report/main.js').read_text(encoding='utf8'))
    expected=expected.replace('__DATA__',payload.group(1))
    assert html==expected
    assert not any(t in html for t in ('__DATA__','__STYLE__','__SCRIPT__'))

    # ----------------------------------------
    # 描画は売買条件と分離し、原本の全清算評価と描画の両極値を再計算する。
    ready,book,*_=study.material(5)
    ledgers=study.load(work/'ledgers/E0_X0.pkl')
    chart_count=chart_points=raw_rows=0
    for case in cases['ケース']:
        key=case['セッション'],case['商品'];r,f=ready[key],book[key]
        ledger=ledgers[key]
        for trade in case['取引']:
            cid=trade['元組番号']-trade['元組番号の起点']
            assert cid==trade['組番号']-1
            original=ledger['trades'][cid]
            start,end=int(original[1]),int(original[2]);side=int(original[3])
            qty=int(original[4]);value=1000 if key[1]=='TOPIX' else 10
            feeunit=41.8 if key[1]=='TOPIX' else 11
            price=f['bid' if side==1 else 'ask'][start:end+1]
            times=r['time_s'][start:end+1]
            net=side*(price-original[5])*qty*value-float(original[7])-math.floor(qty*feeunit+1e-8)
            np.testing.assert_allclose(net[-1],original[10],atol=1e-6,rtol=0)
            np.testing.assert_allclose([net.min(),net.max()],[trade['事後']['MAE円'],trade['事後']['MFE円']],atol=1e-6,rtol=0)
            chart=data['charts'][trade['ID']]
            points=np.asarray(chart['points'],dtype=float)
            assert chart['start']==float(times[0]) and chart['end']==float(times[-1])
            assert points[0].tolist()==[float(times[0]),float(net[0])]
            assert points[-1].tolist()==[float(times[-1]),float(net[-1])]
            assert np.all(np.diff(points[:,0])>=0)
            assert abs(points[:,1].max()-net.max())<1e-6 and abs(points[:,1].min()-net.min())<1e-6
            all_raw={(float(t),round(float(n),6)) for t,n in zip(times,net)}
            assert all((float(t),round(float(n),6)) in all_raw for t,n in points)
            bin_ids=np.floor((times-times[0])/5).astype(int)
            for group in np.unique(bin_ids):
                mask=bin_ids==group
                visible=np.floor((points[:,0]-times[0])/5).astype(int)==group
                assert visible.any()
                assert abs(points[visible,1].min()-net[mask].min())<1e-6
                assert abs(points[visible,1].max()-net[mask].max())<1e-6
            pairing=replays['|'.join(key)]['変更']['E0_X1']['元新規の対応']
            match=[row for row in pairing if row['元組']==cid]
            assert len(match)==1
            chart_count+=1;chart_points+=len(points);raw_rows+=len(times)
    assert chart_count==18

    # ----------------------------------------
    # 結論に使う主条件と遅延感度、正負集計を確認する。
    e={row['id']:row for row in effects}
    for symbol,values in {
        'TOPIX':[-496688,-217524,1229808,60596,2566544,1368232,1833424,1525160,733120,-156928],
        'NK225':[-284400,-114840,772040,-41920,1087960,456560,600320,613320,487640,-156760],
    }.items():
        b=e['E0_X0']['期間'];x=e['E0_X1']['期間']
        actual=[b['赤字上位3'][symbol]['net'],x['赤字上位3'][symbol]['net'],b['残り27'][symbol]['net'],x['残り27'][symbol]['net']]
        actual.extend([r['全30'][symbol][field] for field in ['profit','loss','net'] for r in [b,x]])
        assert actual==values,(symbol,actual)
        for entry in ['E1_X0','E5_X0']:
            for delay in ['1','5','15']:
                assert e[entry]['遅延'][delay][symbol]['net']<e['E0_X0']['遅延'][delay][symbol]['net']
        for exit_id in ['E0_X1','E0_X2']:
            assert e[exit_id]['期間']['全30'][symbol]['net']<0
    readme=(out/'README.md').read_text(encoding='utf8')
    for number in [496688,430000,60000,6688,284400,253000,27000,4400,140836,30836,6440,40440,54440]:
        assert f'{number:,}' in readme,str(number)
    assert '未知の標本を意味しない' in readme and '未来の改善の証明ではない' in readme
    assert '実際の到着順は証明できません' in html
    assert '今回それを有効と確認したわけではありません' in html
    assert '元の基準は全30場・情報遅延3条件とも完全一致' in html

    result=dict(合格=True,公開HTML_SHA256=digest(path),公開会計_SHA256=digest(out/'公開会計.json'),
        公開README_SHA256=digest(out/'README.md'),事前固定_SHA256=digest(work/'事前固定.json'),
        埋込み条件数=len(results),埋込みセッション数=len(data['sessions']),埋込み損益口座数=sum(len(r['rows']) for r in results.values()),
        描画取引数=chart_count,描画点数=chart_points,原本清算評価行数=raw_rows,
        会計と時刻資料の完全一致=True,描画の5秒区間両極値保存=True,全18取引の組番号対応=True,
        解釈=['基準入口を据え置くE0_X1/E0_X2は両商品とも全30場赤字。E4_X1/E4_X2の日経まで赤字とは言わない。',
            '過去の一致を未来需要の保証としない。板の増減から約定・取消・焦りを断定しない。',
            '悪い場の事後診断と全場の実再生を分離し、勝ちを失う負担と新規経路の変化を含む。',
            '未見データの試験でも実受信時計の証明でもない。次の仮説は未確認と明記。'])
    save(HERE/'公開HTMLと会計と描画の最終内容監査.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
