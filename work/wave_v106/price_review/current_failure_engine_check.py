"""一読保存した現在取得・入力False・時計診断の小資料を独立検算する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def clock(value: str) -> datetime:
    """
    機能: 価格時計のISO文字列をtimezone付きの観測値として解釈する。
    引数: value(str)は保存診断にある時計。
    返り値: datetimeは元絶対時計。日付補正や受信時計への変換をしない。
    """
    result=datetime.fromisoformat(value);assert result.tzinfo is not None
    return result


def main() -> None:
    """
    機能: 三小資料の取得完結・失敗扱い・全逆行例の秒差と原行順序を別計算で照合する。
    引数: なし。元三JSONは一読済み私有bundleからのみ参照する。
    返り値: None。新証跡を保存し、原NDJSON/入力gzip/金融/APIを読まない。
    """
    source=HERE/'current_一読した取得失敗と時計診断の資料.json';saved=source.read_bytes();bundle=json.loads(saved)
    capture=bundle['work/wave_v106/current_capture/取得完了.json']['value']
    failed=bundle['work/wave_v106/current_session/現ナイト入力準備False.json']['value']
    diagnostic=bundle['work/wave_v106/current_capture/価格時計逆行による入力停止の非金融診断.json']['value']
    assert capture['全合格'] and diagnostic['診断完了'] and not failed['全合格']
    assert capture['現セッション取得回数']==1 and capture['HTTP要求合計']==2
    assert failed['新金融再生']==failed['API取得']==diagnostic['API取得']==diagnostic['新金融再生']==0
    assert failed['自動再取得'] is False and diagnostic['原本改変']==diagnostic['時刻並べ替え']==diagnostic['時計補完']==0
    assert capture['session']==diagnostic['session']=='2026-10-13_Night'
    assert set(capture['symbols'])==set(diagnostic['商品別'])=={'TOPIX','NK225'}
    assert len({v['snapshot']['generation'] for v in capture['symbols'].values()})==1
    values={};checks=0
    for symbol in ('TOPIX','NK225'):
        fetched=capture['symbols'][symbol];d=diagnostic['商品別'][symbol];snap=fetched['snapshot']
        assert fetched['HTTP要求回数']==1 and fetched['自動再試行']==0 and fetched['curl終了コード']==0
        assert snap['complete']=='true' and snap['code']==symbol and snap['session-id']==capture['session']
        assert d['全行数']==int(snap['sequence']) and d['bytes']==fetched['bytes']
        assert d['最初']['原連番0起点']==0 and d['最後']['原連番0起点']==d['全行数']-1
        assert clock(d['最後']['価格時刻'])<=clock(snap['as-of'])
        assert d['診断目的本文読取']==1 and len(d['SHA256'])==64
        examples=d['最初12逆行例'];assert 0<len(examples)<12
        assert len(examples)==d['直前行からの価格時計逆行'],'上限未満なので掲載例が全逆行例を覆う'
        checked=[];previous=-1
        for e in examples:
            p,e2=e['直前'],e['逆行行'];at=e2['原連番0起点']
            assert at==p['原連番0起点']+1 and previous<at<d['全行数'];previous=at
            before,after=clock(p['価格時刻']),clock(e2['価格時刻']);delta=(before-after).total_seconds()
            assert delta>0 and delta==e['逆行秒']
            assert before.date().isoformat()=='2026-10-14' and after.date().isoformat()=='2026-10-13'
            tod=(after.hour*3600+after.minute*60+after.second)-(before.hour*3600+before.minute*60+before.second)
            assert tod>0 and delta==86400-tod
            checked.append(dict(previous_raw_seq=p['原連番0起点'],raw_seq=at,
                previous_price_clock=p['価格時刻'],price_clock=e2['価格時刻'],absolute_backward_seconds=delta,
                time_of_day_forward_seconds=tod,previous_bid=p['買気配']['Price'],bid=e2['買気配']['Price'],
                previous_ask=p['売気配']['Price'],ask=e2['売気配']['Price']))
            checks+=6
        assert max(e['absolute_backward_seconds'] for e in checked)==d['最大直前逆行秒'];checks+=8
        values[symbol]=dict(全原行数=d['全行数'],全逆行例検算数=len(checked),直前逆行件数=d['直前行からの価格時計逆行'],
            独立最大逆行秒=max(e['absolute_backward_seconds'] for e in checked),全逆行例=checked,
            first_failure_candidate=checked[0],過去最大より古い行の元診断集計=d['過去最大価格時計より古い行'],
            時計欠測の元診断集計=d['時計欠測'],
            集計の検証範囲='直前逆行件数と最大秒差は全掲載例から独立検算。過去最大より古い行数・時計欠測数は根の原本一読集計を引用し、全原行を独立再算定していない。')
    path=HERE/'current_取得完結と逆時計入力失敗の独立確認.json';assert not path.exists()
    output=dict(全合格=True,scope='現在金融の検算でなく、三小資料の取得完結と入力失敗の独立検算。',
        session=capture['session'],商品別=values,逆行例独立検算=checks,掲載全逆行件数=sum(v['直前逆行件数'] for v in values.values()),
        first_failure=dict(商品='TOPIX',原連番0起点=values['TOPIX']['first_failure_candidate']['raw_seq'],
            根の実行報告='NormalCollector.step line205 の価格時計非逆行assert。保存Falseの例外文字列だけでは行番号を独立同定できない。',
            source照合='Normal.stepはBBO/場内採否より前にprevious_timeと比較する。掲載全逆行例の最初TOPIX124773が最初の拒否手掛かり。LPも時計逆行を拒否する。'),
        確認できた事象=['原連番は各例で+1なのに絶対価格時計は約一日戻っている。',
            '全9例の時刻部分だけは1〜101秒進むが、日付は10/14から10/13へ戻る。',
            'HTTP snapshotは両商品同世代で各1要求・Complete true。HTTP完結とアルゴリズム入力資格は別である。'],
        言えないこと=['原行の受信時計がなく、例のCurrentPriceTimeを実到着時刻とは呼べない。',
            '価格時計逆行だけから板価格が虚偽又は売買が不成立だったとは断定できない。',
            '日付を一日足せば正しいと推定して金融へ使うことは今回未検証。',
            '入力失敗は手法の負け/無取引/収支0ではなく、現在答え合わせが未測定という状態。',
            'FalseはAssertionError()のみなので正確なtraceback/失敗位置は根の実行報告と静的sourceへ依存する。'],
        扱い='元取得・False・診断を保持し、再取得/時刻sort/時計補完/source変更なし。登録済み単調時計consumerへ不適合の現在入力を救済せず金融を未測定にする。',
        小資料SHA256={k:v['sha256'] for k,v in bundle.items()},一読保存bundleSHA256=hashlib.sha256(saved).hexdigest(),
        レビューsource_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        元三小JSON各一読=True,原NDJSON読取=0,現在入力gzip読取=0,金融台帳読取=0,金融結果読取=0,
        金融再生=0,API取得=0,source変更=0)
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(path.read_bytes()).hexdigest(),checks,flush=True)


if __name__=='__main__':main()
