"""正式登録の現物だけを確認し、実行中の金融結果は開かない。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[1]
CHECKS=0


def check(value: bool, detail: object) -> None:
    """
    機能: 登録metadataの照合を数える。
    引数: value(bool)、detail(object)。
    返り値: None。
    """
    global CHECKS
    CHECKS+=1
    assert value,detail


def read(path: Path) -> tuple[dict,str]:
    """
    機能: 許可された登録metadataを一回のbytesから読む。
    引数: path(Path) 計画・固定・登録出力。
    返り値: tuple[dict,str] 内容と同bytesの指紋。金融結果へ使わない。
    """
    raw=path.read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def selected_registry(path: Path, identifier: str) -> tuple[dict,str]:
    """
    機能: pretty JSON台帳を行単位で走査し、対象の最上位trial一件だけをdecodeする。
    引数: path(Path)、identifier(str)。
    返り値: tuple[dict,str] 対象一件と読んだ台帳の指紋。原金融ではなく試行登録metadata。
    """
    before=path.stat(); digest=hashlib.sha256()
    rows=[]; head=[]; inside=False; inrow=False; selected=False; resolved=False
    with path.open('rb') as stream:
        for line in stream:
            digest.update(line); mark=line.rstrip(b'\r\n')
            if not inside:
                if mark==b'  "trials": [':inside=True
                continue
            if mark==b'    {':
                check(not inrow,'最上位trial開始境界')
                inrow=True; selected=False; resolved=False; head=[line]
                continue
            if not inrow:continue
            if not resolved:
                head.append(line)
                check(len(head)<30,'idは最上位trial先頭部分')
                if mark.startswith(b'      "id": '):
                    actual=json.loads(mark[len(b'      "id": '):].rstrip(b','))
                    selected=actual==identifier; resolved=True
                    if not selected:head=[]
            elif selected:head.append(line)
            if mark in (b'    },',b'    }'):
                if selected:
                    raw=b''.join(head).rstrip()
                    if raw.endswith(b','):raw=raw[:-1]
                    rows.append(json.loads(raw))
                inrow=False;head=[]
    after=path.stat()
    check((before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'読取中に試行台帳不変更')
    check(len(rows)==1,'実registryの対象trialは一件だけ')
    return rows[0],digest.hexdigest()


def main() -> None:
    """
    機能: 正式計画・登録終端・八部品・現九源を結び、小証跡へ閉じる。
    引数: なし。
    返り値: None。financeの結果本文・NPZ・eventを読まない。
    """
    spec=importlib.util.spec_from_file_location('登録現物の計画定義',BASE/'plan.py')
    plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
    source=plan.sources()
    names=('試行計画.json','金融前の正式固定.json','金融初読前の人工と独立監査.json','入力と保存公開の固定.json',
           '正式照合の全出力.json','正式登録の全出力.json')
    data={}; hashes={}
    for name in names:data[name],hashes[name]=read(BASE/name)
    proposal=data['試行計画.json'];frozen=data['金融前の正式固定.json'];audit=data['金融初読前の人工と独立監査.json'];fixed=data['入力と保存公開の固定.json']
    checked=data['正式照合の全出力.json'];registered=data['正式登録の全出力.json']
    check(checked['終了コード']==registered['終了コード']==0,'正式checkとregisterの終端0')
    result=json.loads(checked['stdout']);entry=json.loads(registered['stdout'])
    check(result['proposal_complete'] is True,'正式checkの完備true')
    check(entry['id']==proposal['id'] and entry['status']=='未実行','登録出力はこの試行を未実行で登録')
    check(entry['spec']==proposal['spec'],'登録stdoutの八部品は正式計画と一致')
    check(entry['preflight']['proposal_complete'] is True,'register内部でも完備true')
    path=ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json'
    actual,registry_sha=selected_registry(path,proposal['id'])
    check(actual['spec']==proposal['spec'] and actual['id']==entry['id'],'実registry行の仕様が正式計画と同一')
    check(actual['preflight']==entry['preflight'],'register出力の内部照合とregistry保存が一致')
    check(source==proposal['spec']['implementation']==frozen['source_SHA256']==audit['source_SHA256'],'現九源・正式計画・固定・根拠束の同一性')
    check(len(source)==9 and audit['全合格'] and audit['新金融']==0,'金融前九源の根拠束')
    for name,key in (('入力と保存公開の固定.json','input_SHA256'),('試行計画.json','proposal_SHA256'),('金融初読前の人工と独立監査.json','audit_SHA256')):
        check(hashes[name]==frozen[key],('正式固定の実ファイル指紋',name))
    evidence=[]
    for item in audit['evidence']:
        raw=(ROOT/item['path']).read_bytes()
        check(hashlib.sha256(raw).hexdigest()==item['SHA256'],('根拠実体の指紋',item['path']))
        evidence.append(item)
    current_view=plan.registration_inputs(fixed)
    check(proposal['spec']['data']['inputs']==current_view,'登録viewだけを変換した66対応')
    check(proposal['spec']['data']['sessions']==fixed['sessions'],'旧33場が同一')
    check(len(fixed['sessions'])==len(set(fixed['sessions']))==33 and len(fixed['inputs'])==66,'33×2個数')
    check(len({(x['raw']['session'],x['raw']['symbol']) for x in fixed['inputs']})==66,'66組の一意性')
    windows={'空':0,'非空':0}
    for raw,view in zip(fixed['inputs'],current_view):
        check(raw['time_policy']==plan.time_policy(raw['raw']['session'],*raw['raw']['bounds']),'実時刻方針の同一性')
        if raw['time_policy']['quiet_windows']==[]:
            check(view['time_policy']['quiet_windows']=='対象窓なし（実行小固定は空配列）','登録だけ対象外表記')
            windows['空']+=1
        else:
            check(view['time_policy']==raw['time_policy'],'実NY静観の数値窓保持')
            windows['非空']+=1
    configs=proposal['spec']['entry']['conditions']
    check(configs==frozen['source_configs'] and len(configs)==12,'登録12経済条件と固定が同一')
    check(proposal['表示主候補']=='QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1','金融結果を見る前の主候補')
    check(frozen['実行予定']==dict(原NPZ=66,保存eventNPZ=66,新金融口座=792,原板=0,API=0),'一回予定の固定')
    for before,after in (('金融初読前の人工と独立監査.json','試行計画.json'),('試行計画.json','金融前の正式固定.json'),
                         ('金融前の正式固定.json','正式照合の全出力.json'),('正式照合の全出力.json','正式登録の全出力.json')):
        check((BASE/before).stat().st_mtime_ns<=(BASE/after).stat().st_mtime_ns,('固定・照合・登録の順序',before,after))
    check(source==plan.sources(),'監査中の九源不変更')
    output=HERE/'正式登録の現物と九源及び時間小固定の独立接続.json'
    proof=dict(全合格=True,確認数=CHECKS,source_SHA256=source,試行ID=proposal['id'],
        公式終端=dict(check=0,register=0,proposal_complete=True,登録時status=entry['status'],現在registry_status=actual['status']),
        metadata_SHA256=hashes,registry_SHA256=registry_sha,evidence=evidence,
        静観窓=windows,実入力予定=frozen['実行予定'],主候補=proposal['表示主候補'],
        未照合の過去あり=bool(result.get('uncomparable')) if 'uncomparable' in result else '正式check.noteの留保を保持',
        重要な区別='登録完了を現物で確認。実行中の金融の成功や利益目標達成を確認したものではない。',
        原NPZ=0,保存eventNPZ=0,金融結果本文=0,金融再生=0,API=0,
        読取補足='正式check/registerのmetadataは最初のGet-Content確認でも読取済み。escaped stdoutが一行のため出力が膨大になり、ここではJSONで構造化して必要項目だけを再確認した。独立市場証拠へ数えない。',
        独立源_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=CHECKS,path=str(output),SHA256=hashlib.sha256(output.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':main()
