"""完成した途中返済のreason9と、三赤字場の出口・追加入口を事後診断する。"""

from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np

import data


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPRESENTATIVES = ('C_N30_B4_THESIS_W10_C5', 'U_P10_B4_THESIS_W30_C5')


def read(path: Path) -> dict:
    """
    機能: 完成済み小会計を読む。
    引数: path(Path)は保存JSON。
    返り値: dictは保存値。新しい売買や原本取得をしない。
    """
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load(item: dict) -> dict:
    """
    機能: 完成台帳を一回読取り、そのbytesと登録SHAを照合する。
    引数: item(dict)は相対path・SHA256。
    返り値: dictは保存台帳。再約定・損益再生をしない。
    """
    content = (ROOT/item['path']).read_bytes()
    assert hashlib.sha256(content).hexdigest() == item['SHA256']
    return pickle.loads(gzip.decompress(content))


def timestamp(value: float) -> str:
    """
    機能: 価格代理時計を日本時間へ表示する。
    引数: value(float)はUNIX秒。
    返り値: strは時刻。真の受信時計とは呼ばない。
    """
    return datetime.fromtimestamp(value, timezone(timedelta(hours=9))).isoformat()


def quote(record: dict, seq: int) -> dict | None:
    """
    機能: 同原seqに対応する既存正常BBOだけを返す。
    引数: record(dict)は正常列、seq(int)は原seq。
    返り値: dict|Noneは同一行のBBO。非対応を隣の行へ補完しない。
    """
    row = int(np.searchsorted(record['seq'], seq))
    if row >= len(record['seq']) or int(record['seq'][row]) != seq:
        return None
    return dict(raw_seq=seq, time=timestamp(float(record['time_s'][row])),
                bid=float(record['bid'][row]), ask=float(record['ask'][row]))


def main() -> None:
    """
    機能: 全792台帳の早期返済数と固定二代表の三赤字場を測る。
    引数: なし。完成thesisと第一51の会計・台帳、三場の準備済cacheだけを読む。
    返り値: None。診断JSONを新保存する。金融再生・原板・APIは0。
    """
    target = HERE/'理由9と三赤字場の出口及び追加入口.json'
    assert not target.exists()
    path = HERE/'finance/results.json'
    finished = read(path)
    first = read(ROOT/'work/wave_v106/finance/results.json')
    assert finished['全合格'] and finished['account_count'] == 792
    # ----------------------------------------
    # 事後の診断対象は基準C_N30_B4のTOPIX赤字上位3場。商品円額を合算選定しない。
    selected = sorted([row for row in first['cases']['C_N30_B4']['rows']
        if row['symbol'] == 'TOPIX' and row['net'] < 0], key=lambda row:(row['net'],row['session']))[:3]
    sessions = [row['session'] for row in selected]
    summaries, kept, hashes = {}, {}, {}
    count = 0
    for config in finished['configs']:
        ident = config['id']
        summaries[ident] = {}
        for symbol in ('TOPIX','NK225'):
            stats = dict(実親=0, 理由9親=0, 理由9利益=0, 理由9損失=0, 理由9収支=0.)
            for session in finished['sessions']:
                item = finished['cases'][ident]['ledgers'][session][symbol]
                saved = load(item)
                count += 1
                hashes[item['path']] = item['SHA256']
                early = saved['trades'][saved['trades'][:,13] == 9]
                stats['実親'] += len(saved['trades'])
                stats['理由9親'] += len(early)
                stats['理由9利益'] += int(np.count_nonzero(early[:,11] > 1e-5))
                stats['理由9損失'] += int(np.count_nonzero(early[:,11] < -1e-5))
                stats['理由9収支'] += float(early[:,11].sum())
                if ident in REPRESENTATIVES and session in sessions:
                    kept[(ident,symbol,session)] = saved
            assert stats['実親'] == finished['cases'][ident]['summary'][symbol]['campaigns']
            stats['対照差額'] = finished['diagnosis'][ident][symbol]
            summaries[ident][symbol] = stats
    assert count == 792
    scenes = []
    configs = {value['id']:value for value in finished['configs']}
    for session in sessions:
        packet = data.load_session(session)
        for ident in REPRESENTATIVES:
            config = configs[ident]
            for symbol in ('TOPIX','NK225'):
                record = packet['prepared'][symbol]['record']
                peer_record = packet['prepared']['NK225' if symbol=='TOPIX' else 'TOPIX']['record']
                case = packet['cases'][config['entry_id']][symbol]
                decisions = {int(v['row']):v for v in case['decisions']}
                obs = packet['peers'][symbol][str(config['thesis_window'])]
                changed = kept[(ident,symbol,session)]
                item = first['cases'][config['base_id']]['ledgers'][session][symbol]
                baseline = load(item)
                hashes[item['path']] = item['SHA256']
                before = {str(int(v['decision_seq']))+'|'+str(int(v['direction'])):v
                          for v in baseline['trade_details']}
                after = {}
                early_records, added = [], []
                for trade in changed['trades']:
                    row, side = int(trade[15]),int(trade[4])
                    key = str(int(record['seq'][row]))+'|'+str(side)
                    after[key] = trade
                    if key not in before:
                        evidence = decisions[row]
                        added.append(dict(判断時刻=timestamp(float(record['time_s'][row])),
                            判断原seq=int(record['seq'][row]), 新規約定時刻=timestamp(float(record['time_s'][int(trade[2])])),
                            新規価格=float(trade[6]), 方向='買い' if side==1 else '売り',
                            支持=float(evidence['support_price']), 支持根拠=evidence['selected_support_roots'],
                            根拠種別=evidence.get('family',config['entry_id']),
                            相手入口判定=evidence.get('peer_status','自己入口は相手条件を使わない'),
                            最終収支=float(trade[11]), 注意='元は別保有で参加できなかった入口を含む。新しい予測法で創作した入口ではない。'))
                    if trade[13] != 9:
                        continue
                    order = changed['orders'][(changed['orders'][:,2]==trade[0]) & (changed['orders'][:,7]==0)][0]
                    exit_decision = int(order[1])
                    line = changed['thesis_judgments']
                    selected_line = line[(line[:,2]==trade[0]) & (line[:,0]==exit_decision)][-1]
                    floats, integers = obs['float_lineage'][exit_decision], obs['integer_lineage'][exit_decision]
                    early_records.append(dict(新規判断時刻=timestamp(float(record['time_s'][row])),
                        新規判断原seq=int(record['seq'][row]), 新規価格=float(trade[6]), 初期支持=float(selected_line[5]),
                        方向='買い' if side==1 else '売り', 返済判断時刻=timestamp(float(order[10])),
                        返済判断原seq=int(record['seq'][exit_decision]), 判断自己bid=float(record['bid'][exit_decision]),
                        判断自己ask=float(record['ask'][exit_decision]), 支持逆破れ呼値=side*(selected_line[5]-selected_line[4])/record['tick'],
                        確認開始時刻=timestamp(float(selected_line[9])), 確認継続秒=float(selected_line[10]),
                        相手公表時刻=timestamp(float(floats[0])), 相手年齢秒=float(floats[1]),
                        相手bid変化呼値=float(floats[2]), 相手ask変化呼値=float(floats[3]),
                        相手公表原seq=int(integers[0]), 相手基準原seq=int(integers[1]),
                        相手当時BBO=quote(peer_record,int(integers[0])), 相手基準BBO=quote(peer_record,int(integers[1])),
                        返済約定時刻=timestamp(float(order[11])), 返済価格=float(trade[7]), 最終収支=float(trade[11]),
                        対応する元結果=before.get(key),
                        出口差=float(trade[11]-before[key]['net']) if key in before else None))
                removed = [value for key,value in before.items() if key not in after]
                common = set(before) & set(after)
                contribution = dict(避けた基準損失=sum(-v['net'] for v in removed if v['net']<0),
                    失った基準利益=sum(v['net'] for v in removed if v['net']>0),
                    共通入口の出口変化=sum(float(after[k][11])-before[k]['net'] for k in common),
                    新たな入口の収支=sum(v['最終収支'] for v in added))
                contribution['収支変化'] = (contribution['避けた基準損失']-contribution['失った基準利益']
                    +contribution['共通入口の出口変化']+contribution['新たな入口の収支'])
                base_row = next(v for v in first['cases'][config['base_id']]['rows'] if v['session']==session and v['symbol']==symbol)
                new_row = next(v for v in finished['cases'][ident]['rows'] if v['session']==session and v['symbol']==symbol)
                assert abs(contribution['収支変化']-(new_row['net']-base_row['net']))<1e-4
                scenes.append(dict(session=session,condition=ident,symbol=symbol, 基準収支=base_row['net'],
                    改修収支=new_row['net'],差額分解=contribution,理由9の実返済=early_records,新しい入口=added,
                    見送った元取引=removed))
    proof = dict(全合格=True,全33まとめ=summaries, 三赤字場=sessions, 具体診断=scenes,
        選定='同数量基準C_N30_B4のTOPIX赤字上位3場。日経も同じ場を対照。事後診断であり入口条件へ渡さない。',
        代表=REPRESENTATIVES, 台帳読取=792+12,途中入力読取=3, 新金融再生=0,原本読取=0,API取得=0,
        source_SHA256={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest(),
            'work/wave_v106/thesis/diagnosis.py':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        ledger_SHA256=hashes,
        限界='早い返済は基準損失を減らしても回復利益を切り、参加時刻を変える。単一親の出口差と後続入口全体の効果を混同しない。33場は既知、配信時計は不明。')
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(全合格=True,対象3場=sessions,実台帳=count,具体口座=len(scenes),新金融再生=0),ensure_ascii=False))


if __name__=='__main__':
    main()
