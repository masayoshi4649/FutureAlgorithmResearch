"""保存E01入口を六つの当時二市場条件で事後分類する。新売買は作らない。"""

import argparse
import gc
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time
import traceback

import numpy as np

import core


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REFERENCE = ROOT/'work/wave_v106/e01_reference'
SYMBOLS = ('TOPIX', 'NK225')
DAILY = 'E01_DAILY_P1_L8'


def read(path: Path) -> object:
    """
    機能: 小JSONまたは既存packetを同bytesで読み、SHAを照合できるよう返す。
    引数: path(Path)は保存ファイル。
    返り値: objectは保存内容。原本/API/新注文の実行は行わない。
    """
    content = path.read_bytes()
    if path.suffix == '.json':
        return json.loads(content.decode('utf-8-sig'))
    return pickle.loads(gzip.decompress(content) if path.suffix == '.gz' else content)


def digest(path: Path) -> str:
    """
    機能: 小さい既存資料の内容指紋を求める。
    引数: path(Path)はsourceまたはJSON。
    返り値: strはSHA256。巨大packetは別関数の同読取bytesで確認する。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    """
    機能: 新所有領域へ新規UTF-8 JSONを保存する。
    引数: path(Path)、value(dict)は位置と値。
    返り値: None。旧資料および既保存結果は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
        encoding='utf-8', newline='\n')


def checked_packet(item: dict) -> dict:
    """
    機能: 登録指紋と同じ既packetを一回のbytes読取で返す。
    引数: item(dict)はroot相対pathとSHA256。
    返り値: dictは不変packet。原本を再抽出しない。
    """
    path = ROOT/item['path']; before = path.stat(); content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == item['SHA256'], path
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    return pickle.loads(gzip.decompress(content))


def freeze() -> dict:
    """
    機能: 価格窓・六条件・母集団・読取計画を、新分類の値を見る前に保存する。
    引数: なし。
    返り値: dictは読取固定。金融再生の登録計画とは別の事後分類計画。
    """
    old = read(ROOT/'work/wave_v104/入口準備の全32結果.json')
    day = read(ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json')
    thesis = read(ROOT/'work/wave_v106/thesis/全33場の途中相手準備.json')
    reference = read(REFERENCE/'結果.json'); qmeta = read(REFERENCE/'prepared/入力準備の完了.json')
    daily = read(ROOT/'work/wave_v106/e01_daily/finance/結果.json')
    assert all(x['全合格'] for x in (old, day, thesis, reference, qmeta, daily))
    sessions = qmeta['全33']; assert len(sessions) == 33 and sessions == thesis['sessions']
    assert set(sessions) == set(old['sessions']) | {day['session']}
    data = dict(sessions=sessions, packets={s: dict(day if s == day['session'] else old['cache'][s]) for s in sessions},
        thesis={s: thesis['cache'][s] for s in sessions},
        q=dict(path='work/wave_v106/e01_reference/prepared/quotes.pkl', SHA256=qmeta['全気配SHA256']),
        baseline_ledgers={p:h for p,h in reference['台帳SHA256'].items() if p.startswith('ledgers/L_D20_BBO/')})
    assert len(data['baseline_ledgers']) == 66
    small = [p for p in HERE.glob('*.py')]+[HERE/'二市場入口分類の人工検査.json',
        ROOT/'work/wave_v104/入口準備の全32結果.json',
        ROOT/'work/wave_v104/holdout_input/追加Dayの活動と19入口.json',
        ROOT/'work/wave_v106/thesis/全33場の途中相手準備.json',
        ROOT/'work/wave_v106/e01_daily/finance/結果.json', REFERENCE/'結果.json',
        REFERENCE/'prepared/入力準備の完了.json', ROOT/'work/wave_v104/peer/prices.py']
    value = dict(全合格=True, data=data, source_SHA256={p.relative_to(ROOT).as_posix():digest(p) for p in small},
        条件=[dict(id=mode+str(w), window_seconds=w,
            意味='既知相手が元方向と逆でなければ許可' if mode=='N' else '自己相手双方のbid/askが元方向へ1呼値以上進行')
            for w in core.WINDOWS for mode in ('N','P')],
        入口時点=['紙上新規source行', '実指値到達fill行'],
        公表='価格clockの新最大最初原行。自己は当原行以下、相手はstrictpastかつ15秒以内。',
        過去基準='公表終点-W以下の最新公表源。W秒より古い余分な経過は15秒以下。',
        資格='104端点qualified/BBO・inclusive price reset/seq/clock・publicgap・spread曖昧を維持。60だけ資格式変更なし。',
        分析='保存親の事後分類と料金後会計の足算。新しい入口/注文/政策再生ではない。',
        母集団=['全33の保存L_D20_BBO実新規全件', 'P1L8黒字/赤字/無取引の場別最初の実入口',
            'P1L8停止行までの実新規接頭全件'],
        未来ラベル='元親損益と政策結果は集計用のみ。観測/採否関数へ渡さない。', 新金融=0, 新注文=0, 原本再読取=0, API=0)
    write(HERE/'分析事前計画.json', value)
    return value


def locate(raw: dict, seq: int, stamp: float, bid: float, ask: float) -> int:
    """
    機能: E01正常行を原seq完全一致で104原行へ対応させる。
    引数: raw(dict)、seq(int)、stamp/bid/ask(float)は元正常行の実値。
    返り値: intは一致原行。不一致を次正常行へ移動しない。
    """
    position = int(np.searchsorted(raw['raw_seq'], seq)); assert position < len(raw['raw_seq'])
    assert int(raw['raw_seq'][position]) == seq and raw['price_time_s'][position] == stamp
    for value, expected in ((raw['bid'][position], bid), (raw['ask'][position], ask)):
        assert value == expected or (np.isnan(value) and np.isnan(expected))
    return position


def metric(entries: list[dict]) -> dict:
    """
    機能: 保存親の料金後収支を、そのまま正負に分けて足し合わせる。
    引数: entries(list[dict])は当時情報で分類済みの保存親。
    返り値: dictは件数・利益・損失・収支。新金融による成績とは呼ばない。
    """
    gains = [e['baseline_parent_net'] for e in entries if e['baseline_parent_net'] > 0]
    losses = [-e['baseline_parent_net'] for e in entries if e['baseline_parent_net'] < 0]
    gain, loss = float(sum(gains)), float(sum(losses))
    return dict(件数=len(entries), 勝ち件数=len(gains), 負け件数=len(losses), 利益=gain, 損失=loss,
        収支=gain-loss, PF=gain/loss if loss else None,
        勝率=len(gains)/len(entries) if entries else None)


def statistics(entries: list[dict], sessions: list[str]) -> dict:
    """
    機能: 紙上/実fill各6条件について、前16・後17・全33の静的G/Lを求める。
    引数: entries(list[dict])、sessions(list[str])は保存分類と場順。
    返り値: dictは捨てる利益・回避候補損失・no-data。動的再生効果と区別する。
    """
    output = {}
    for stage in ('paper','fill'):
        output[stage] = {}
        for window in core.WINDOWS:
            for mode in ('N','P'):
                ident = mode+str(window); output[stage][ident] = {}
                for symbol in SYMBOLS:
                    output[stage][ident][symbol] = {}
                    for period, subset in (('前16',sessions[:16]),('後17',sessions[16:]),('全33',sessions)):
                        original = [e for e in entries if e['symbol']==symbol and e['session'] in subset]
                        accepted = [e for e in original if e['stages'][stage]['gates'][ident]['accepted']]
                        rejected = [e for e in original if not e['stages'][stage]['gates'][ident]['accepted']]
                        reason = {label:sum(e['stages'][stage]['gates'][ident]['reason']==label for e in original)
                            for label in ('UNKNOWN','AMBIGUOUS','相手逆方向','同方向支持なし','採用')}
                        before, kept, dropped = metric(original), metric(accepted), metric(rejected)
                        assert np.isclose(before['収支'],kept['収支']+dropped['収支'],atol=1e-5)
                        output[stage][ident][symbol][period] = dict(母集団=before, 採用群=kept, 不採用群=dropped,
                            捨てる基準利益=dropped['利益'], 除外される基準損失=dropped['損失'],
                            静的収支差=kept['収支']-before['収支'], 判定理由件数=reason,
                            静的採用のある場数=len({e['session'] for e in accepted}),
                            静的採用ゼロ場数=len(subset)-len({e['session'] for e in accepted}))
    return output


def daily_groups(entries: list[dict], daily: dict) -> dict:
    """
    機能: P1L8の結果群を、最初の実入口と停止前全入口を分けて事後比較する。
    引数: entries(list[dict])、daily(dict)は保存分類と完了小利益政策。
    返り値: dictは群別の当時採否件数。政策結果を観測条件へ逆流させない。
    """
    rows = {(r['session'],r['symbol']):r for r in daily['results'][DAILY]['rows']}
    controls = {(r['session'],r['symbol']):r for r in daily['発動'][DAILY]}
    groups = {}
    for symbol in SYMBOLS:
        groups[symbol] = {}
        for label in ('利益目標を得て黒字','初期損失のまま赤字','無取引'):
            selected_sessions = [s for (s,p),r in rows.items() if p==symbol and
                ((label=='利益目標を得て黒字' and r['収支']>0)
                 or (label=='初期損失のまま赤字' and r['収支']<0)
                 or (label=='無取引' and r['親数']==0))]
            first, prefix = [], []
            for session in selected_sessions:
                subset = [e for e in entries if e['session']==session and e['symbol']==symbol]
                if not subset:
                    continue
                first.append(min(subset,key=lambda e:e['fill_row']))
                control = controls[session,symbol]
                limit = control['判断行'] if control['発動'] else np.inf
                prefix.extend(e for e in subset if e['fill_row']<=limit)
            counts = {}
            for sample_label, sample in (('各活動場の最初の実入口',first),('停止前全実入口',prefix)):
                counts[sample_label] = {}
                for stage in ('paper','fill'):
                    counts[sample_label][stage] = {mode+str(w):dict(
                        accepted=sum(e['stages'][stage]['gates'][mode+str(w)]['accepted'] for e in sample),
                        total=len(sample),
                        acceptance_rate=sum(e['stages'][stage]['gates'][mode+str(w)]['accepted'] for e in sample)/len(sample) if sample else None,
                        UNKNOWN=sum(e['stages'][stage]['gates'][mode+str(w)]['reason']=='UNKNOWN' for e in sample),
                        AMBIGUOUS=sum(e['stages'][stage]['gates'][mode+str(w)]['reason']=='AMBIGUOUS' for e in sample))
                        for w in core.WINDOWS for mode in ('N','P')}
            groups[symbol][label] = dict(場数=len(selected_sessions), sessions=selected_sessions,
                測定=counts, 母集団注記='結果で分けた群の入口状態。P(黒字|状態)と反転して説明しない。')
    return groups


def run() -> None:
    """
    機能: 保存33packetと66実台帳を一回読み、当時六分類と静的対照を作る。
    引数: なし。
    返り値: None。新金融・新注文・旧paper・原本/APIは全てゼロ。
    """
    started = time.monotonic(); plan = read(HERE/'分析事前計画.json')
    assert not (HERE/'入口状態と保存損益の分類.json').exists() and not (HERE/'分析失敗.json').exists()
    for name,wanted in plan['source_SHA256'].items():
        assert digest(ROOT/name)==wanted,name
    qspec=plan['data']['q']; qpath=ROOT/qspec['path']; qbytes=qpath.read_bytes()
    assert hashlib.sha256(qbytes).hexdigest()==qspec['SHA256']; quotes=pickle.loads(qbytes); del qbytes
    daily=read(ROOT/'work/wave_v106/e01_daily/finance/結果.json')
    entries=[]; checks=[]; board_examples=[]; sessions=plan['data']['sessions']; window_columns=0; peer_checks=0
    try:
        for session in sessions:
            packet=checked_packet(plan['data']['packets'][session])
            if 'peer' in packet:
                packet=packet['peer']
            thesis=checked_packet(plan['data']['thesis'][session]); assert packet['session']==thesis['session']==session
            features={}
            for symbol in SYMBOLS:
                raw=packet['raw'][symbol]; old=packet['peer_features'][symbol]
                features[symbol]=core.public_windows(raw,old['public'],float(packet['items'][symbol]['tick']),packet['policy'])
                window_columns+=core.compare_legacy(features[symbol],old)
            for symbol in SYMBOLS:
                raw=packet['raw'][symbol]; other='NK225' if symbol=='TOPIX' else 'TOPIX'; q=quotes[session,symbol]
                oldrecord=packet['normal'][symbol]['record']; record=thesis['prepared'][symbol]['record']
                for name in ('seq','time_s','bid','ask'):
                    np.testing.assert_array_equal(oldrecord[name],record[name])
                    np.testing.assert_array_equal(q[name],record[name])
                relative=f'ledgers/L_D20_BBO/{session}_{symbol}.pkl.gz'
                base=checked_packet(dict(path=(REFERENCE/relative).relative_to(ROOT).as_posix(),
                    SHA256=plan['data']['baseline_ledgers'][relative]))
                new_orders=base['orders'][base['orders'][:,7]==1]
                assert len(new_orders)==len(base['parent'])
                parent_by_id={int(p['親']):p for p in base['parent']}
                first_fill=min([int(o[0]) for o in new_orders],default=None)
                for o in new_orders:
                    fill,paper,parent,side=map(int,(o[0],o[1],o[2],o[3]))
                    entry=dict(session=session,symbol=symbol,parent=parent,side=side,quantity=int(o[4]),
                        fill_row=fill,paper_row=paper,baseline_parent_net=parent_by_id[parent]['収支'],stages={})
                    for stage,row in (('paper',paper),('fill',fill)):
                        stamp=float(q['time_s'][row]); seq=int(q['seq'][row])
                        rawrow=locate(raw,seq,stamp,float(q['bid'][row]),float(q['ask'][row]))
                        values={}; gates={}
                        for window in core.WINDOWS:
                            own=core.observe(raw,features[symbol],stamp,window,rawrow,False)
                            peer=core.observe(packet['raw'][other],features[other],stamp,window,None,True)
                            if window in (10,30):
                                previous=thesis['peers'][symbol][str(window)]
                                # peer資格は自己尾部と独立。既保存strictpast投影の方向と数値を照合する。
                                assert peer['known']==bool(previous['known'][row]),(session,symbol,row,window)
                                if peer['known']:
                                    assert peer['direction']==int(previous['direction'][row])
                                    assert peer['source']['raw_seq']==int(previous['integer_lineage'][row,0])
                                    assert peer['reference']['raw_seq']==int(previous['integer_lineage'][row,1])
                                    np.testing.assert_array_equal([peer['bid_change_ticks'],peer['ask_change_ticks']],
                                        previous['float_lineage'][row,2:4])
                                peer_checks+=1
                            values[str(window)]=dict(own=own,peer=peer)
                            for mode in ('N','P'):
                                accepted,reason=core.acceptance(own,peer,side,mode)
                                gates[mode+str(window)]=dict(accepted=accepted,reason=reason)
                        entry['stages'][stage]=dict(row=row,seq=seq,time_s=stamp,current=core.quote(raw,rawrow),
                            windows=values,gates=gates)
                    entries.append(entry)
                    if fill==first_fill:
                        board_examples.append(entry)
                checks.append(dict(session=session,symbol=symbol,entries=len(new_orders),seq_time_BBO_exact=True,
                    保存全入口枚数一致=True,新金融=0))
            print(session+' 紙上/実指値の六分類完了・新注文0',flush=True)
            del packet,thesis,features,base
            gc.collect()
        statistics_value=statistics(entries,sessions); grouped=daily_groups(entries,daily)
        assert all(digest(ROOT/name)==wanted for name,wanted in plan['source_SHA256'].items())
        write(HERE/'入口状態と保存損益の分類.json',dict(全合格=True,sessions=sessions,entries=entries,
            静的六条件=statistics_value,P1L8結果群の当時入口=grouped,最初の入口の具体気配=board_examples,
            照合=checks,十秒三十秒保存全列同値=window_columns,保存相手投影同値=peer_checks,
            旧104packet読取=33,既途中packet読取=33,E01気配pickle読取=1,基準実台帳読取=66,
            新金融再生=0,新注文=0,元paper再生=0,原板再読取=0,API=0,
            分類計画SHA256=digest(HERE/'分析事前計画.json'),source開始終端一致=True,
            限界=['保存済み親の事後選別会計。指値が未到達の紙上候補は母集団に含まない。',
                '新規採否が後の保有と場内停止を変える実政策の成績は未検証。',
                '同PriceTime内の公表後変化は公表方向へ混ぜない。ReceivedAtがなく同時配信順は証明できない。',
                'UNKNOWNは支持なしという既知情報ではない。104と同じ資格が取引頻度を落とす場合を表示する。',
                '結果群を分けた採用率P(状態|政策結果)をP(政策結果|状態)へ逆転しない。全33は既知。'],
            経過秒=time.monotonic()-started))
        print('全33の当時入口分類・保存会計静的集計完了。新金融0',flush=True)
    except Exception:
        write(HERE/'分析失敗.json',dict(全合格=False,原因=traceback.format_exc(),完了口座=len(checks),
            新金融再生=0,新注文=0,自動再実行=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='保存E01の当時二市場入口だけを事後分類する')
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--root-observed-classification',action='store_true')
    args=parser.parse_args()
    if args.freeze:
        assert not args.root_observed_classification
        freeze()
    else:
        assert args.root_observed_classification,'新金融でない保存入口の分類だけを根指定後に実行'
        run()
