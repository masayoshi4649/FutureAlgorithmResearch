"""保有期限を使わない13方向定義を、損益を見る前に固定して因果照合する。"""
from pathlib import Path
import hashlib
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
from signals import MODELS, TURN_TICKS, SPANS, THRESHOLDS, COMBINATIONS, market_features, project, build_session


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    """
    機能: ファイルを分割読取し、内容指紋を取得する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''): h.update(block)
    return h.hexdigest()


# ----------------------------------------
def specification():
    """
    機能: 新損益を参照せず13状態の数値条件と観測限界を定める。
    引数: なし。
    返り値: dict の事前仕様。
    """
    return {
        '目的':'その場の方向状態が変われば注文を判断するための状態系列。保有秒数、固定利確幅、未来の極値は定義しない。',
        '損益参照':False,'現在API取得':0,'実注文':0,
        'モデル順序':MODELS,
        '自己時計':'自己の原板行iを読み、その行までの気配・数量を状態へ反映して判断する。原本保存順で既読なら同じCurrentPriceTimeの後続行も更新に使う。',
        '相手時計':'自己の現在代理時計tより厳密に小さい相手時計の最新値を探し、その時計の先頭行まで計算された状態を用いる。同時計後続行や同時刻の相手行を使わない。',
        '時計の限界':'CurrentPriceTimeは最終約定時計の代理。自己の保存順は観測順と仮定するが、真の受信時刻・二市場同期・同時計内の時間間隔は再現できない。',
        '鮮度':'自己は現在行でage0。相手はt−参照時計が正で10秒以内。最新候補が無効でも古い良い板へ戻らない。相手3秒鮮度は別の品質感度として後で制限できる。',
        '有効板':'方向状態は有限の正の最良価格・正の最良数量・bid<askだけで有効判定する。旧book.validの完全10段条件、旧book.resetは使わない。最良気配か最良表示数量が変わった既読原板を更新イベントとする。',
        '新規品質':'price_valid_self/peer/両方は、方向用の最良正常性にspread<=1ラージ呼値を追加した新規用の品質。方向のvalidとは別であり、spread拡大で方向履歴を消さない。相手は鮮度10秒以内も要求。',
        '履歴初期化':'各セッションを独立に初期化。代理時計間隔、気配差拡大、原本seq飛び、10段不正、出来高resetでは方向・観測極値・EMA履歴を消さない。最良が無効ならその行の状態valid=false。D1は最後の有効方向・観測極値を保ち、復帰後の実観測中値で継続又は反転を判定。途中に未観測の極値は推定しない。自己時計逆転は入力準備段階で拒否し、計算核も仮に発生すれば全初期化する。',
        'OFI比較元の扱い':'最良無効又は原本seqが非連続なら、前後の気配差を新しいOFIと数えない。比較元だけを破棄し、既存EMA分子分母と非ゼロ件数は維持する。復帰の最初の行は基準を置き直し、flow_comparable=falseでD2/D3は無効、次の連続した正常行から比較を再開する。最良無効期間を反対方向と誤認しない。',
        '売買損益前の時計仕様修正':'旧版をpreclockfixへ保存した後、代理時計gap>10秒だけによる履歴初期化を除去した。CurrentPriceTimeの停滞は板観測欠落と同義ではなく、方向を時間のみで消さないための修正。売買損益はまだ計算・参照していない。相手鮮度10秒は同期品質判定として維持。',
        '計算開始後の品質欠陥修正':'初回86条件の計算開始直後、損益を一切閲覧する前に停止。旧版と未閲覧の部分結果はprequalityfixに保存した。方向状態出現数の不足を調べ、正常なspread>1呼値で履歴を消す設計と、最良のみの指標へ10段品質を流用する問題を特定して修正。損益の良否に合わせた修正ではない。',
        '原本seq飛びの意味':'旧抽出は最良不正・ロック板・交差板・時刻欠測・時間外を除外する。監査で今回の内部除外9640行は売買同値9275行と売買逆転365行、正常最良板の除外0、飛び6039箇所、時計逆転0と確認。D2比較元だけの破棄に用い、D1の極値を消す根拠にはしない。',
        'D1':'k=1,2,4,8。各場の最初の有効中値を基準に±k呼値進めば方向確定。上向き時は以後の最高中値を更新し、そこからk呼値下がると下向きへ反転。下向きは最安値からk呼値上がると上向きへ反転。中値変位閾値であり売買利確幅ではない。反転時は現在中値を次方向の極値とする。',
        '最良OFI':'e=1(b>=b前)q買−1(b<=b前)q買前−1(a<=a前)q売+1(a>=a前)q売前。全既読原板の最良価格・数量変化から求め、成行/取消/補充を識別したとはみなさない。',
        'D2':'非ゼロOFIの有効イベントだけでN=8,32,128のEMAを更新。alpha=2/(N+1)、分子=EMA(e)、分母=EMA(abs(e))、比を方向指標とする。各N件が揃うまでは未準備。比>=.15/.30で買い、<=−.15/−.30で売り、その間は有効な中立。数値閾値比較は保存float32比で行う。',
        'イベント数の意味':'Nは秒でも分でもない。非ゼロOFIが止まればEMAは減衰せず最後の値を保持する。last_flow_updateで根拠の最終更新行を追える。同数量同価格の重複だけでは更新しない。',
        'D3':'D1/D2が両方有効かつ同方向の場合だけその方向。k2/N32/.15、k4/N32/.15、k4/N128/.30の3組。その他の組合せを損益で追加しない。',
        '二市場':'各自己原板行で双方の同じモデルが有効かつ同方向のときだけstates=±1。両方有効でも不一致又は中立ならstates=0、valid=true。欠測・未準備ならvalid=false。片側対照はstates_self/valid_selfで方向を取り、取引可能な価格品質を共通化するかは注文側の事前仕様に従う。',
        '未定義':'信号イベントから新規・返済・ドテンを発注するルール、発注5秒待ちと取消、緊急停止は注文エンジン側。状態準備は損益・建玉に依存しない。',
        '後半':'既知30場を前16と後14へ分ける。後14も未知の将来ではない。方向仕様は新しい損益計算前に固定する。'
    }


# ----------------------------------------
def truncated(record, length):
    """
    機能: 原板対応の配列だけを指定行までに物理的に切り詰める。
    引数: record (dict)、length (int)。
    返り値: dict の未来行を含まない入力。
    """
    size=len(record['time_s'])
    return {k:v[:length] if isinstance(v,np.ndarray) and v.ndim and len(v)==size else v for k,v in record.items()}


# ----------------------------------------
def prefix_check(ready, books, session, result):
    """
    機能: 自己原板途中3地点で未来を除き、相手strictpastを含む全出力を照合する。
    引数: ready/books/result (dict)、session (str)。
    返り値: int の照合口座地点数。
    """
    checks=0
    for symbol in ('TOPIX','NK225'):
        peer='NK225' if symbol=='TOPIX' else 'TOPIX'
        r=ready[(session,symbol)]; p=ready[(session,peer)]; n=len(r['time_s'])
        for fraction in (.2,.5,.8):
            count=max(1,int(n*fraction)); deadline=r['time_s'][count-1]
            peer_count=max(1,int(np.searchsorted(p['time_s'],deadline,side='left')))
            a=market_features(truncated(r,count),truncated(books[(session,symbol)],count))
            b=market_features(truncated(p,peer_count),truncated(books[(session,peer)],peer_count))
            candidate=project(a,b); full=result[(session,symbol)]
            for field,value in candidate.items():
                if not isinstance(value,np.ndarray):continue
                expected=full[field][:,:count] if value.ndim==2 else full[field][:count]
                assert np.array_equal(value,expected,equal_nan=True),(session,symbol,fraction,field)
            checks+=1
    return checks


# ----------------------------------------
def main():
    """
    機能: 同じ保存30場から方向状態と事前仕様、未来切断の照合証跡を保存する。
    引数: なし。
    返り値: None。今回のprepared/design以外へ書き込まない。
    """
    prepared=HERE/'prepared'; design=HERE/'design'
    prepared.mkdir(exist_ok=True);design.mkdir(exist_ok=True)
    meta_path=ROOT/'work/wave_v77/inputs/metadata.json'
    meta=json.loads(meta_path.read_text(encoding='utf-8')); sessions=meta['sessions']
    assert len(sessions)==30
    inputs={};paths={}
    for kind,extra in (('ready','extra_inputs.pkl'),('features','extra_features.pkl')):
        paths[kind]=[ROOT/p for p in meta['input_paths'][kind]]+[ROOT/'work/wave_v77/inputs'/extra]
        inputs[kind]={}
        for path in paths[kind]:
            with path.open('rb') as stream:part=pickle.load(stream)
            assert not set(inputs[kind])&set(part)
            inputs[kind].update(part)
    ready,books=inputs['ready'],inputs['features']
    spec=specification();spec['全30']=sessions;spec['前16']=sessions[:16];spec['後14']=sessions[16:]
    spec['コードSHA256']={n:digest(HERE/n) for n in ('signals.py','prepare.py')}
    spec['入力SHA256']={str(p.relative_to(ROOT)):digest(p) for group in paths.values() for p in group}
    spec['原本SHA256']={str(p.relative_to(ROOT)):digest(p) for session in sessions for s in ('TOPIX','NK225') for p in [ROOT/'book'/s/(session+'.jsonl')]}
    (design/'方向仕様.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
    output={};rows=[];checks=0
    for session in sessions:
        result=build_session(ready,books,session)
        checks+=prefix_check(ready,books,session,result)
        for (session,symbol),signal in result.items():
            peer='NK225' if symbol=='TOPIX' else 'TOPIX';n=len(signal['time_s'])
            assert np.array_equal(signal['source_self'],np.arange(n))
            source=signal['source_peer'];known=source>=0;times=ready[(session,peer)]['time_s']
            assert np.all(times[source[known]]<signal['time_s'][known])
            assert np.array_equal(np.searchsorted(times,times[source[known]],side='left'),source[known])
            assert np.all(~signal['valid_peer'][:,known] | (signal['age_peer'][known] <= 10.))
            assert np.all(signal['states'][~signal['valid']]==0)
            assert np.all(np.isin(signal['states'],[-1,0,1]))
            rows.append(dict(セッション=session,商品=symbol,原板行数=n,
                             自己価格有効行=int(signal['price_valid_self'].sum()),二市場価格有効行=int(signal['price_valid'].sum()),
                             モデル={m['id']:dict(自己状態行=int(np.count_nonzero(signal['states_self'][i])),
                                                     二市場状態行=int(np.count_nonzero(signal['states'][i])),二市場有効行=int(signal['valid'][i].sum()),
                                                     自己非ゼロ状態変更数=int(np.sum((signal['states_self'][i,1:]!=signal['states_self'][i,:-1])&(signal['states_self'][i,1:]!=0))))
                                     for i,m in enumerate(MODELS)}))
        output.update(result)
        print(json.dumps(dict(準備済み=session),ensure_ascii=False),flush=True)
    target=prepared/'signals.pkl'
    with target.open('wb') as stream:pickle.dump(output,stream,protocol=5)
    proof=dict(全合格=True,口座数=len(output),原板行合計=sum(r['原板行数'] for r in rows),方向定義数=len(MODELS),
               未来切断照合数=checks,自己既読現在行=True,相手厳密過去時計先頭=True,相手有効鮮度10秒以内=True,
               中立と欠測の分離=True,状態行数は取引数ではない=True,各場=rows,
               signals_SHA256=digest(target),方向仕様_SHA256=digest(design/'方向仕様.json'),新損益参照=False,現在API取得=0,実注文=0)
    (prepared/'方向準備と因果照合.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    schema=dict(キー='(session,symbol)',行数='自己のready.time_sと一致。time_s[i]でcurrent行まで処理して判断。',
                配列={'states_self/states_peer/states':'int8[13,n]、モデル順は方向仕様のモデル順序。statesは二市場同方向のみ。',
                      'valid_self/valid_peer/valid':'bool[13,n]。0方向が中立か欠測か必ずこの配列で分ける。',
                      'source_self/source_peer':'int32[n]、原本準備行。peer=-1は過去参照なし。古い相手行は索引を残しvalid=false。',
                      'time_self/time_peer/age_self/age_peer':'参照時計と古さ。自己age0、相手age>10は無効。',
                      'bid/ask/bid_qty/ask_qty と _peer':'実際の参照気配・数量。無効品質をvalidで判断する。',
                      'flow_self/flow_peer':'float32[3,n]、span8/32/128。未準備でも途中比を診断用に保持、有効性はvalid。',
                      'flow_count_self/flow_count_peer':'int32[n]、場内の有効な非ゼロOFI件数。原本行飛びの比較元置き直しでは件数を消さない。',
                      'last_flow_update_self/peer・last_quote_update_self/peer':'int32[n]、根拠更新行。peerの値は相手市場の準備行。',
                      'turn_extreme_self/peer・last_price_turn_self/peer':'[4,n]、k1/2/4/8の現在方向の極値・最後の確定反転行。',
                      'price_valid/price_valid_self/price_valid_peer':'bool[n]、新規用の最良正常かつspread<=1呼値。方向validとは別。',
                      'direction_price_valid_self/peer':'bool[n]、方向用の最良正常性。spread拡大や完全10段欠測で履歴を消さない。',
                      'flow_comparable_self/peer・flow_rebase_self/peer':'bool[n]、OFIを前気配と比較できるか・比較元を置き直したか。EMAは保持。',
                      'entry_reset':'bool[n]、今回準備は時刻単調増加・場独立なので全False。旧book.resetを注文制御に流用しない。'},
                注意='二市場方向は自己原板の各行で評価。同一代理時計でも自己状態が変わり得る。相手状態を同時計後続行まで先読みしない。')
    (design/'連携する列と読み方.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k!='各場'},ensure_ascii=False))


if __name__=='__main__': main()
