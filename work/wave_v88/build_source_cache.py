"""固定3源の公開注文を一度だけ作り、旧仕様対照を確認する。新成績の選別はしない。"""
from pathlib import Path
import importlib.util
import json
import pickle
import sys
import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('wave88_sources',HERE/'sources.py')
sources=importlib.util.module_from_spec(spec);sys.modules[spec.name]=sources;spec.loader.exec_module(sources)
prepare=sources.prepare


def main():
    """
    機能: 全源を同入力へ接続し、旧紙上台帳との一致だけを集計する。
    引数: なし。
    返り値: None。新しい合計損益・配分順位は算出又は表示しない。
    """
    output=HERE/'prepared/source_orders.pkl'
    assert not output.exists(),'源注文は固定後に上書きしません'
    inputs,signals,input_hashes=prepare.prepare85.load_inputs(verify=True)
    candle_hashes={f'candle_1min/{key[1]}/{key[0]}.csv':prepare.sha(ROOT/'candle_1min'/key[1]/(key[0]+'.csv')) for key in inputs}
    features=sources.initialize(inputs,signals)
    legacy_engine=prepare.module('wave88_legacy19_engine',ROOT/'work/wave_v19/engine.py')
    legacy_signals=prepare.module('wave88_legacy17_signals',ROOT/'work/wave_v17/signals.py')
    original_m3=pickle.loads((ROOT/'work/wave_v19/全取引台帳.pkl').read_bytes())
    original_c03=pickle.loads((ROOT/'work/wave_v52/ledgers.pkl').read_bytes())['C03']
    original_gu=pickle.loads((ROOT/'work/wave_v85/observed/ledgers/E01_G_U.pkl').read_bytes())
    results={};proof=[]
    old_sessions=sorted({key[1] for key in original_m3 if key[0]=='V0800'})
    added_sessions=['2026-09-28_Day','2026-09-28_Night','2026-09-29_Day']
    oldstates=pickle.loads((ROOT/'work/wave_v17/主方向状態.pkl').read_bytes())
    for key,ready in sorted(inputs.items()):
        account={};checks=dict(session=key[0],symbol=key[1])
        for sid in ('GU','M3','C03'):
            account[sid]=sources.play(sid,key,ready,features)
        np.testing.assert_array_equal(account['GU']['orders'],original_gu[key]['orders'])
        checks['GU旧注文完全一致']=True
        if key in original_c03:
            _,native=sources.c03_native(ready,features[key]['C03'])
            np.testing.assert_array_equal(native,np.asarray(original_c03[key]['orders']))
            checks['C03旧注文完全一致']=True
        # ----------------------------------------
        # M3の指定価格対照だけは元の既知13場へ限定し、新観測版の成績を比較しない。
        if key[0] in old_sessions+added_sessions:
            direction=features[key]['M3']
            old=legacy_engine.run(ready,direction,sources.M3_FIXED['一枚でのエンジン設定'],detail=True)
            copied=sources.m3.run(ready,direction,sources.M3_FIXED['一枚でのエンジン設定'],detail=True,observed_fill=False)
            for name in ('orders','trades','cycles','curve','stats'):np.testing.assert_array_equal(old[name],copied[name])
            checks['M3指定Falseの旧実装全配列一致']=True
            if key[0] in old_sessions:
                for name,value in original_m3[('V0800',*key)].items():np.testing.assert_array_equal(old[name],value)
                np.testing.assert_array_equal(direction,-oldstates[key]['M3'])
                checks['M3旧保存全台帳一致']=True
            else:
                path=ROOT/'work/wave_v21'/key[0]/'features'/f'{key[1]}_{key[0]}.csv'
                frame=pd.read_csv(path)
                peer=(key[0],'NK225' if key[1]=='TOPIX' else 'TOPIX')
                independently=legacy_signals.build_states(ready,inputs[peer],features=frame)
                np.testing.assert_array_equal(direction,-independently['M3'])
                record=json.loads((ROOT/'work/wave_v21'/key[0]/'再生記録.json').read_text(encoding='utf-8'))
                recorded=[t for t in record['trades'] if t['symbol']==key[1]]
                assert len(recorded)==len(old['trades'])
                for past,tr in zip(recorded,old['trades']):
                    assert past['side']==('買い' if tr[2]>0 else '売り') and past['quantity']==tr[3]
                    assert past['entry_price']==tr[4] and past['exit_price']==tr[5]
                    assert pd.Timestamp(past['entry_time']).timestamp()==ready['time_s'][int(tr[6])]
                    assert pd.Timestamp(past['exit_time']).timestamp()==ready['time_s'][int(tr[7])]
                    assert past['reason']==legacy_engine.REASONS[int(tr[9])]
                checks['M3追加旧3場の保存全取引一致']=True
        results[key]=account;proof.append(checks)
        print('源注文・旧対照確認 '+str(key),flush=True)
    output.write_bytes(pickle.dumps(results,pickle.HIGHEST_PROTOCOL))
    used=['sources.py','source_prepare.py','m3_engine.py','c03_observe.py','build_sources.py','build_source_cache.py']
    code={f'work/wave_v88/{name}':prepare.sha(HERE/name) for name in used}
    code.update({str(Path(mod.__file__).relative_to(ROOT)).replace('\\','/'):prepare.sha(Path(mod.__file__)) for mod in (legacy_engine,legacy_signals,sources.old)})
    comparison_files=['work/wave_v19/全取引台帳.pkl','work/wave_v52/ledgers.pkl','work/wave_v85/observed/ledgers/E01_G_U.pkl']
    comparison_files += [f'work/wave_v21/{session}/再生記録.json' for session in added_sessions]
    for name,digest in candle_hashes.items():assert prepare.sha(ROOT/name)==digest,name
    proofdoc=dict(全合格=True,全30=sorted({key[0] for key in inputs}),入力SHA256=input_hashes,一分足SHA256=candle_hashes,
        旧対照SHA256={name:prepare.sha(ROOT/name) for name in comparison_files},源注文SHA256=prepare.sha(output),実装SHA256=code,各口座=proof,
        GU旧注文一致口座=sum(v.get('GU旧注文完全一致',False) for v in proof),
        C03旧注文一致口座=sum(v.get('C03旧注文完全一致',False) for v in proof),
        M3指定旧13場全実装一致口座=sum(v.get('M3指定Falseの旧実装全配列一致',False) for v in proof),
        成績選定='紙上注文を生成したが、新源成績・配分を集計又は選別していない。源3つと仕様は事前指定通り。',
        配列列=sources.ORDER_COLUMNS,源固定条件=sources.declarations(),
        価格層='紙上源は観測CurrentPriceで独立運転。その約定が当行に公開され、実配分口座は次の有効共通観測で追従。')
    prepare.save(HERE/'prepared/準備完了.json',proofdoc)


if __name__=='__main__':main()
