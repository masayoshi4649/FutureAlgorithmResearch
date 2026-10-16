"""一回取得した未完了ナイトの固定三政策を、実現と残建玉評価を分けて表示する。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import math
from pathlib import Path


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
PUBLIC=ROOT/'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'
TITLE='現在ナイト一回照合の途中損益'
ACCOUNTING_TITLE='現在ナイト一回照合の途中会計.json'
SESSION='2026-10-13_Night'
SYMBOLS=('TOPIX','NK225')
IDENTIFIERS=('AUTO_ER40_M2_LIMIT','R_ONLY_ER40_M2_LIMIT','C_ONLY_B2_ER40_B4')
RESULT=HERE/'current_session/finance/結果.json'
METADATA=HERE/'current_session/未完了ナイトの入力準備.json'
CAPTURE=HERE/'current_capture/取得完了.json'
FIELDS=('realized_profit','realized_loss','realized_net','open_mark_net','actual_liquidation_value',
        'held_long','held_short','pending_entry','pending_exit','total_paid_fees','reserved_exit_fees')
JAPAN=timezone(timedelta(hours=9))


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 完成小JSONを同じbytes一回で読み、出典指紋を保存する。
    引数: path(Path)は結果又は取得/入力metadata。板・gzip・台帳は読まない。
    返り値: tuple[dict,str]は保存値とSHA256。
    """
    saved=path.read_bytes()
    return json.loads(saved),hashlib.sha256(saved).hexdigest()


def build(result: dict, metadata: dict, capture: dict, fingerprints: dict) -> dict:
    """
    機能: 事前固定三政策の接頭会計と取得由来を検算し、六行の表示値へ対応させる。
    引数: result/metadata/capture/fingerprints(dict)は完成小結果・入力・取得証跡・指紋。
    返り値: dictは途中会計。欠測を0へ補完せず、不一致又は未完成は拒否する。
    """
    assert result['全合格'] and metadata['全合格'] and capture['全合格']
    assert result['session']==metadata['session']==capture['session']==SESSION
    assert result['finish'] is False and metadata['finish'] is False and result['途中終端']
    assert result['accounts']==6 and result['新接頭金融口座']==6
    assert result['API取得']==result['実注文']==result['原本読取']==0
    assert capture['現セッション取得回数']==1 and capture['HTTP要求合計']==2
    assert result['configs']==metadata['configs']
    assert [v['id'] for v in result['configs']]==list(IDENTIFIERS)
    assert set(result['cases'])==set(IDENTIFIERS)
    assert result['入力metadataSHA256']==fingerprints[METADATA.relative_to(ROOT).as_posix()]
    assert metadata['取得manifestSHA256']==fingerprints[CAPTURE.relative_to(ROOT).as_posix()]
    assert result['入力gzipSHA256']==metadata['cache']['SHA256']
    assert result['開始終端source一致'] and metadata['開始終端source一致']
    rows=[];clocks={}
    for symbol in SYMBOLS:
        fetched=capture['symbols'][symbol];snap=fetched['snapshot'];input_value=metadata['accounts'][symbol]
        assert fetched['HTTP要求回数']==1 and fetched['自動再試行']==0 and fetched['curl終了コード']==0
        assert snap['session-id']==SESSION and snap['code']==symbol and snap['complete']=='true'
        assert input_value['source_snapshot']['as_of']==datetime.fromisoformat(snap['as-of'].replace('Z','+00:00')).isoformat()
        assert input_value['source_snapshot']['generation']==snap['generation']
        clocks[symbol]=dict(as_of=snap['as-of'],capture_start=fetched['取得開始'],capture_end=fetched['取得完了'],
            last_price_clock=input_value['最後の価格代理時計'],normal_limit=input_value['通常limit'],
            snapshot_sequence=int(snap['sequence']),generation=snap['generation'])
    for identifier in IDENTIFIERS:
        config=next(v for v in result['configs'] if v['id']==identifier)
        assert config['quantity']=={'TOPIX':5,'NK225':10} and config['caps']=={'TOPIX':10,'NK225':20}
        for symbol in SYMBOLS:
            account=result['cases'][identifier][symbol]
            assert account['symbol']==symbol and account['finish'] is False
            assert all(account[k] for k in ('closed_trade_verification','all_row_order_equity_verification',
                'realized_plus_open_verification','pending_zero_exposure_verification'))
            values={k:account[k] for k in FIELDS}
            assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values.values())
            assert values['realized_profit']>=0 and values['realized_loss']>=0
            assert abs(values['realized_profit']-values['realized_loss']-values['realized_net'])<1e-4
            assert abs(values['realized_net']+values['open_mark_net']-values['actual_liquidation_value'])<1e-4
            for key in ('held_long','held_short','pending_entry','pending_exit'):
                assert values[key]>=0 and values[key]==int(values[key])
            assert not (values['held_long'] and values['held_short'])
            assert account['last_price_clock']==clocks[symbol]['last_price_clock']
            rows.append(dict(id=identifier,symbol=symbol,**values,closed_campaigns=account['closed_campaigns'],
                quote_invalid_at_end=account['quote_invalid_at_end'],clearing_quote_row=account['clearing_quote_row'],
                last_price_clock=account['last_price_clock'],last_raw_seq=account['last_raw_seq']))
    return dict(session=SESSION,rows=rows,clocks=clocks,configs=result['configs'],sources=fingerprints,
        途中終端=True,条件再選択=0,追加取得=0,新金融再生=0,E01の未見検証='未測定',
        表示範囲='取得済み接頭。全ナイトの収支ではない。')


def number(value: float, digits: int=0) -> str:
    """
    機能: 検算済み有限値を桁区切りで表示する。
    引数: value(float)は表示値、digits(int)は小数桁数。
    返り値: strは有限数値。未知値を0へ変換しない。
    """
    assert math.isfinite(value)
    return format(value,',.'+str(digits)+'f')


def clock_text(value: object) -> str:
    """
    機能: 実取得ISO時計又は価格代理epochを日本時間として別表示する。
    引数: value(str|float)は保存時計。原行受信時計は生成しない。
    返り値: strは日本時間の表示。timezone不明は拒否する。
    """
    stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else datetime.fromtimestamp(value,JAPAN)
    assert stamp.tzinfo is not None
    return stamp.astimezone(JAPAN).isoformat(timespec='seconds').replace('T',' ')


def render(data: dict) -> str:
    """
    機能: 六つの接頭会計と二商品の異なる観測上限を短いダークHTMLへ描画する。
    引数: data(dict)は検算済み表示資料。
    返り値: strは通信/売買を含まないHTML。残玉評価を決済済み利益へ混ぜない。
    """
    labels={'AUTO_ER40_M2_LIMIT':'往復なら反発・同方向なら追従',
        'R_ONLY_ER40_M2_LIMIT':'往復範囲内の端で反発を待つ',
        'C_ONLY_B2_ER40_B4':'二市場同方向の板支持で追従'}
    body=[]
    for row in data['rows']:
        cells=[]
        for field in FIELDS:
            value=row[field];color='positive' if value>0 and field not in ('realized_loss','total_paid_fees','reserved_exit_fees') else 'negative' if value<0 or (field=='realized_loss' and value>0) else ''
            cells.append('<td class="'+color+'">'+number(value)+'</td>')
        body.append('<tr><td>'+labels[row['id']]+'<small>'+row['id']+'</small></td><td>'+('TOPIXミニ' if row['symbol']=='TOPIX' else '日経マイクロ')+'</td>'+''.join(cells)+'</tr>')
    clock_rows=[]
    for symbol,clocks in data['clocks'].items():
        values=(clocks['as_of'],clocks['capture_start'],clocks['capture_end'],clocks['last_price_clock'])
        clock_rows.append('<tr><td>'+symbol+'</td>'+''.join('<td>'+html.escape(clock_text(v))+'</td>' for v in values)+'</tr>')
    css='*{box-sizing:border-box}body{margin:0;background:#0b1120;color:#dce4f2;font:16px/1.6 system-ui}main{max-width:1370px;margin:auto;padding:26px 20px}h1{font-size:26px}h2{font-size:20px}p{margin:12px 0}small{display:block;font-size:12px;color:#aabbce}a{color:#8fbeff}.scroll{overflow:auto;margin:18px 0;max-width:100%}table{border-collapse:collapse;font-size:14px;width:100%;min-width:1280px}th,td{padding:11px 12px;border-bottom:1px solid #33425a;text-align:right;white-space:nowrap}th{background:#1d2c43}td:first-child,th:first-child{text-align:left}tbody tr:nth-child(even){background:#152135}.positive{color:#57ddb1}.negative{color:#ff9196}.note{color:#acbbcf}table.clocks{min-width:980px}@media(max-width:600px){main{padding:16px 12px}h1{font-size:23px}}'
    headings=('手法','商品','確定利益','確定損失','確定収支','残玉評価\n往復料込','合計清算代理','買い保有','売り保有','新規待機','返済予約','支払済み料','残返済料')
    table='<div class="scroll"><table id="accounts"><thead><tr>'+''.join('<th>'+html.escape(v).replace('\n','<br>')+'</th>' for v in headings)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
    return '<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+TITLE+'</title><style>'+css+'</style></head><body><main><h1>'+TITLE+'</h1><p><b>2026-10-13 ナイトの取得済み途中まで。固定3条件の答え合わせで、全ナイトの最終成績ではありません。</b></p><p>TOPIXミニ初回5枚・上限10枚、日経マイクロ初回10枚・上限20枚。金額は円、建玉・待機は枚です。</p>'+table+'<p>確定利益・損失は返済済み取引の手数料後金額。残玉評価は未返済建玉を最後の正常気配で清算した場合の代理額で、新規料と残返済料を含みます。<b>合計清算代理＝確定収支＋残玉評価</b>。新規待機には建玉損益を付けません。</p><p>反発側は固定指値で待ち、範囲外の停止線又は中心への到達で返済を判断。追従側は元の板支持と停止・追尾を使用します。途中でモードが変わっただけでは返済しません。</p><h2>取得と観測の上限</h2><div class="scroll"><table id="clocks" class="clocks"><thead><tr><th>商品</th><th>HTTP固定上限 AsOf</th><th>実取得開始</th><th>実取得完了</th><th>最終価格代理時計</th></tr></thead><tbody>'+''.join(clock_rows)+'</tbody></table></div><p class="note">二商品の固定上限は個別です。実取得時刻・AsOf・価格代理時計はいずれも原行の受信時計ではありません。原行の受信時計は不明です。末尾気配が不正なら直前の正常気配で評価します。実注文は0、今回の取得は両商品各1回だけ、取得後の追加取得・条件再探索は0です。</p><p class="note">この3条件はR_PRICEと旧Cの未見比較で、<b>E01新候補の未見試験は行っていません（未測定）</b>。ミニ/マイクロの実板や指値待ち順位は再現していません。通常返済期限は変更せず、取得終端で架空の全返済をしません。</p><p><a href="README.md">調査状況</a> · <a href="E01の取引更新と損失幅の改善及び全セッション損益.html">E01の既知33場比較</a></p></main></body></html>'


def run(destination: Path) -> None:
    """
    機能: 根CLIの指示時に完成小結果だけを読み、途中HTMLと表示会計を指定先へ保存する。
    引数: destination(Path)は根が指定する出力先。
    返り値: None。未完成時は出力せず待機。板・入力gzip・金融・ネットワークを実行しない。
    """
    missing=[p.name for p in (RESULT,METADATA,CAPTURE) if not p.exists()]
    if missing:print('現在ナイトの完成資料待ち：'+', '.join(missing));return
    values={};fingerprints={}
    for path in (RESULT,METADATA,CAPTURE):
        value,digest=read(path);values[path]=value;fingerprints[path.relative_to(ROOT).as_posix()]=digest
    data=build(values[RESULT],values[METADATA],values[CAPTURE],fingerprints)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/(TITLE+'.html')).write_text(render(data),encoding='utf8',newline='\n')
    (destination/ACCOUNTING_TITLE).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(dict(全合格=True,表示口座=len(data['rows']),途中終端=True,E01未見='未測定',新金融再生=0,API=0),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='固定3政策の未完了ナイト表示のみ')
    parser.add_argument('--output-dir',type=Path,default=PUBLIC);args=parser.parse_args();run(args.output_dir)
