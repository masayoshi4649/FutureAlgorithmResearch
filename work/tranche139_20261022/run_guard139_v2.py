"""早期の繰返し損失と指標発表時刻の損失へ、因子を分けて対処する。"""

import argparse
import copy
import pickle
import subprocess
import sys
from pathlib import Path
import numpy as np
from common139 import HERE,ROOT,read,save,ref,account
import early139
import early_guard139_v2 as early_guard139

MANAGER=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def described(value):
    """
    機能: 説明用の空配列を未記入と区別する。
    引数: value(dict/list/str/float/bool)は設定値。
    返り値: 同型又はstrは説明版。実行条件の空配列自体は変更しない。
    """
    if isinstance(value,dict):return {k:described(v) for k,v in value.items()}
    if isinstance(value,list):return [described(v) for v in value] if value else '追加なし'
    return value


def prepare():
    """
    機能: 原因を見て導いた追加比較を固定し、既知探索として登録する。
    引数: なし。
    返り値: None。保存会計による原因分析と新しい金融再生を分離する。
    """
    p=copy.deepcopy(read(HERE/'早期計画.json'))
    p.update(id='139_早期参加の再試行と急変時刻の制御_ID修正',name='損失反復・狭幅・指標発表時刻の分離改善',configs=early_guard139.settings(),
        question='早期の短い支持を繰り返し追った損失を、再試行の終了、幅の拡大、初回のみ、時刻静観で改善できるか。',
        change='元の早期E01/E15の候補は固定。損失回数1/2、管理R2倍、追加なし、夜の米寄り75～45分前静観を別因子で比較。',
        repeat_reason='E01の9/28日経ナイト9親全敗、10/14TOPIX21:30気配飛び等を診断。損切り反復と単発ショックを混同しない。',
        compares_to=['139_朝と米国前の早期参加'])
    p['spec']['entry']={'条件':described(early_guard139.settings()),'入口候補':'元E01とE15を変更しない。両市場の支持は元の短Rで正規化。','通常担当':'B5/C04は早期が保有中の候補だけ見送り、返済後の新しい候補は参加。'}
    p['spec']['management']={'停止':'早期の全玉実返済後の親損益が費用後マイナスなら回数を一度だけ加算。1/2回で当該早期窓の新規停止。通常担当は継続。',
        '幅':'管理用のATRと最低幅だけ2倍。入口支持の正規化は不変。初回のみは追加玉を0にする。',
        '時刻':'対象日は選ばず全ナイトで米寄り75分前に返済し45分前まで早期新規禁止。区間前の未約定を静観帯へ持ち込まない。朝は同じ比較条件のまま。'}
    p['spec']['exit']={'早期':'各玉の停止・利益追尾、09:50/米寄り15分前返済を維持。静観条件のみ米寄り75分前にも返済。',
        '通常':'採用した通常親の返済は保存条件のまま。'}
    for name in ('run_guard139_v2.py','early_guard139_v2.py'):
        r=ref(HERE/name);p['spec']['implementation'][r['path']]=r['sha256']
    p['evidence']=[ref(HERE/'early_guard_v2_人工確認.json'),ref(HERE/'early_diagnosis139.json')]
    p['external_source']={'url':'https://www.bls.gov/schedule/2026/10_sched_list.htm','observed':'2026-10-22',
        'finding':'10/14米東部08:30にCPI予定。当該板の21:30急変と時刻一致。ニュースが唯一の原因とは断定しない。日付を選別せず毎夜同じ静観帯を使う。'}
    save(HERE/'早期改善_v2計画.json',p)
    for action in ('check','register'):
        r=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),action,'--proposal',str(HERE/'早期改善_v2計画.json')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        save(HERE/f'早期改善_v2_{action}.json',dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,r.stderr[-2000:]
        print(action,'完了',flush=True)


def run():
    """
    機能: 改善条件を全47場へ適用し、単独と通常併用を別口座で会計する。
    引数: なし。
    返り値: None。止めたことによる逸失利益も全場の収支へ反映する。
    """
    plan=read(HERE/'早期改善_v2計画.json');assert read(HERE/'早期改善_v2_register.json')['returncode']==0;assert plan['configs']==early_guard139.settings()
    for path,sha in plan['spec']['implementation'].items():assert ref(ROOT/path)['sha256']==sha,path
    main=[read(HERE/f'{folder}/結果.json') for folder in ('results','extra_results')]
    baseline={(r['session'],r['symbol']):r for d in main for r in d['cache']}
    packets=read(HERE/'manifest139.json')['packets']+read(HERE/'manifest139_extra.json')['packets'];rows=[];cache=[];skips=[]
    for p in packets:
        assert ref(Path(p['path']))['sha256']==p['sha256'];packet=pickle.loads(Path(p['path']).read_bytes());scene=p['session']
        prepared=early139.prepare(packet);arrays={s:{} for s in ('NK225','TOPIX')};saved={};signals={}
        for c in plan['configs']:
            if c['source'] not in signals:signals[c['source']]=early139.candidates(prepared,c['entry'])
        for source,symbols in signals.items():
            for symbol,ready in symbols.items():arrays[symbol]['source_'+source]=ready['core_candidates']
        for symbol in arrays:
            r=baseline[(scene,symbol)];assert ref(ROOT/r['path'])['sha256']==r['sha256']
            with np.load(ROOT/r['path'],allow_pickle=False) as f:saved[symbol]={key:f[key] for key in ('B5','C04')}
        for c in plan['configs']:
            for symbol,ready in signals[c['source']].items():
                for basekey in ('単独','B5','C04'):
                    key=c['id'] if basekey=='単独' else basekey+'_'+c['id'];base=np.empty((0,10)) if basekey=='単独' else saved[symbol][basekey]
                    orders,skipped=early_guard139.joined(base,ready['core_candidates'],ready,c['management'],symbol,c['guard'])
                    arrays[symbol][key]=orders;row=account(orders,ready['time_s'],ready['quotes'],key,scene,symbol)
                    row['early_entries']=int(np.sum((orders[:,7]==1)&(orders[:,8]==0)&(orders[:,2]>=20000))) if len(orders) else 0;rows.append(row)
                    if skipped:skips.append(dict(method=key,session=scene,symbol=symbol,skipped=skipped))
        for symbol,content in arrays.items():
            target=HERE/'guard_results/measurement'/f'{symbol}_{scene}.npz';target.parent.mkdir(parents=True,exist_ok=True);assert not target.exists()
            np.savez_compressed(target,**content);cache.append(dict(session=scene,symbol=symbol,**ref(target)))
        print(scene,'早期の損失反復改善完了',flush=True)
    save(HERE/'guard_results/結果.json',dict(rows=rows,cache=cache,skips=skips,plan=ref(HERE/'早期改善_v2計画.json'),API=0,real_orders=0))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('prepare','run'));args=p.parse_args();{'prepare':prepare,'run':run}[args.stage]()
