"""凍結監査の並列全件結果を、各条件証跡・原本指紋・根の全値から独立に受け入れる。"""

import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=WORK.parents[1]
PARALLEL=WORK/'audit_parallel'
COUNT=Counter()


def read(path: Path) -> dict:
    """
    機能: 完成後のJSONだけを独立読取する。
    引数: path(Path)。
    返り値: dict、保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 全保存ファイルをSHA256で照合する。
    引数: path(Path)。
    返り値: str、SHA256。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):value.update(block)
    return value.hexdigest()


def compare(first: object,second: object,path: str) -> None:
    """
    機能: 全階層を別読取で比較し、根の期間及び安定性値の省略を拒絶する。
    引数: first/second(object)、path(str)。
    返り値: None、元凍結監査と同じ絶対許容1e-5で全値を確認する。
    """
    if isinstance(first,dict):
        assert isinstance(second,dict) and first.keys()==second.keys(),(path,'辞書構造')
        for key,value in first.items():compare(value,second[key],path+'/'+str(key))
    elif isinstance(first,list):
        assert isinstance(second,list) and len(first)==len(second),(path,'配列長')
        for i,(a,b) in enumerate(zip(first,second)):compare(a,b,path+'/'+str(i))
    elif isinstance(first,(int,float)) and not isinstance(first,bool):
        assert isinstance(second,(int,float)) and math.isfinite(first) and math.isfinite(second),path
        assert math.isclose(first,second,abs_tol=1e-5,rel_tol=0),(path,first,second)
        COUNT['数値セル独立照合']+=1
    else:assert first==second,(path,first,second)


def hashes(mapping: dict) -> None:
    """
    機能: 目録の全指紋を実保存資料へ独立に対応付ける。
    引数: mapping(dict[str,str])。
    返り値: None、最初の不一致で停止する。
    """
    for relative,expected in mapping.items():
        assert digest(ROOT/relative)==expected,relative
        COUNT['指紋独立照合']+=1


def main() -> None:
    """
    機能: 全53再検算の最終証跡を受け入れ、中断された途中監査を流用せず記録する。
    引数: なし。
    返り値: None、新audit受入JSON。凍結181依存及び並列元証跡は変更しない。
    """
    fixed_path=WORK/'事前固定.json';fixed=read(fixed_path)
    full_path=HERE/'full.py';driver_path=PARALLEL/'driver.py'
    evidence_path=PARALLEL/'並列実行_全53条件全31場の価格入口と別執行源及び全原板会計と安定性の独立検算.json'
    proof_path=PARALLEL/'凍結監査の全手順同一と実行並列化及び依存名補足.json'
    manifest_path=PARALLEL/'実行前凍結と全手順.json';analysis_path=WORK/'analysis/比較結果.json'
    evidence,proof,manifest,analysis=map(read,(evidence_path,proof_path,manifest_path,analysis_path))
    assert proof['全合格'] and evidence['全合格'] and analysis['全合格']
    assert len(fixed['SHA256'])==181 and len(fixed['条件'])==53
    assert proof['事前固定SHA256']==manifest['事前固定SHA256']==digest(fixed_path)
    assert proof['凍結fullSHA256']==manifest['凍結fullSHA256']==digest(full_path)==fixed['SHA256'][str(full_path.relative_to(ROOT))]
    hashes(fixed['SHA256']);hashes(proof['読取監査SHA256']);hashes(proof['証跡SHA256']);hashes(evidence['SHA256'])
    assert proof['固定181依存変更']==proof['凍結監査ファイル変更']==proof['凍結検算関数変更']==0
    assert proof['元main前後前提及び後段省略なし'] and proof['全53条件省略なし']
    assert manifest['ドライバSHA256']==digest(driver_path)
    tree=ast.parse(full_path.read_text(encoding='utf-8'))
    original=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    location=[i for i,node in enumerate(original.body) if isinstance(node,ast.For) and isinstance(node.target,ast.Name)
              and node.target.id=='config' and isinstance(node.iter,ast.Name) and node.iter.id=='conditions']
    assert len(location)==1;index=location[0]
    before=original.body[:index];loop=original.body[index:index+1];after=original.body[index+1:-1];last=original.body[-1:]
    def ast_hash(nodes: list) -> str:
        """
        機能: 元mainの各構文領域を独立に内容指紋化する。
        引数: nodes(list[ast.stmt])。
        返り値: str、位置属性を除くSHA256。
        """
        text=ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False)
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    ast_proof=proof['構文木同一性']
    assert ast_proof==manifest['構文木同一性']
    for key,nodes in (('元main全体構文木SHA256',original.body),('分割再結合構文木SHA256',before+loop+after+last),
                      ('前提構文木SHA256',before),('条件ループ構文木SHA256',loop),
                      ('後段照合構文木SHA256',after),('元保存呼出構文木SHA256',last)):
        assert ast_proof[key]==ast_hash(nodes),key
    assert len(original.body)==ast_proof['元main文数']==ast_proof['再結合文数']==26
    driver=ast.parse(driver_path.read_text(encoding='utf-8'))
    changes=[target.attr for node in ast.walk(driver) if isinstance(node,ast.Assign) for target in node.targets
             if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='full']
    assert changes==['state_checks'],changes
    assert proof['不足依存名補足']==manifest['不足依存名補足']
    assert '末尾指紋収集' in proof['不足依存名補足']['作用']
    conditions=fixed['条件'];ids=[config['id'] for config in conditions]
    checkpoint_hashes=proof['全53チェックポイントSHA256']
    assert len(checkpoint_hashes)==53
    assert {path.stem for path in (PARALLEL/'checkpoints').glob('*.json')}==set(ids)
    assert {Path(relative).stem for relative in checkpoint_hashes}==set(ids)
    hashes(checkpoint_hashes)
    totals=Counter();assembled={};period_names=set();accounts=0
    bindings={}
    for config in conditions:
        path=PARALLEL/'checkpoints'/(config['id']+'.json');checkpoint=read(path)
        assert checkpoint['全合格'] and checkpoint['条件']==config
        assert checkpoint['事前固定SHA256']==digest(fixed_path) and checkpoint['凍結fullSHA256']==digest(full_path)
        assert checkpoint['条件ループ構文木SHA256']==ast_proof['条件ループ構文木SHA256']
        hashes(checkpoint['SHA256'])
        assert set(checkpoint['全31独立会計'])=={config['id']}
        values=checkpoint['全31独立会計'][config['id']]
        compare(values,evidence['全31独立会計'][config['id']],config['id']+'/checkpoint最終一致')
        expected={name:analysis['results'][config['id']][name] for name in ('rows','periods','stability')}
        compare(values,expected,config['id']+'/analysis全値一致')
        assert len(values['rows'])==62
        assert {(row['session'],row['symbol']) for row in values['rows']}=={(session,symbol) for session in fixed['全31'] for symbol in ('TOPIX','NK225')}
        assert set(values['periods'])==set(values['stability'])=={'全31','前16','後15','旧30','後14','追加1','デイ','ナイト'}
        period_names.update(values['periods']);accounts+=len(values['rows'])
        for period in values['periods']:
            assert set(values['periods'][period])==set(values['stability'][period])=={'TOPIX','NK225'}
            COUNT['商品期間独立照合']+=2
        totals.update(checkpoint['検査件数']);assembled[config['id']]=values
        bindings[str(path.relative_to(ROOT))]=digest(path)
    assert set(assembled)==set(evidence['全31独立会計'])==set(analysis['results'])==set(ids)
    compare(dict(totals),evidence['検査件数'],'全件検査数の独立加算')
    compare(dict(totals),proof['検査件数'],'同一手順証明の独立加算')
    assert accounts==totals['口座']==3286 and COUNT['商品期間独立照合']==totals['商品期間集計']==848
    assert totals['注文']==11320 and totals['決済親']==totals['保有途中の最初返済条件']==5660
    assert totals['全原板行']==totals['全行価格と執行源の独立対応']==419839871
    assert sum(row['campaigns'] for values in assembled.values() for row in values['rows'])==5660
    completed=[ident for worker in proof['worker完了'] for ident in worker['完了条件']]
    assert len(completed)==53 and set(completed)==set(ids)
    assert all(worker['全完了'] for worker in proof['worker完了'])
    boundary_path=HERE/'全3286口座の運用区切りと連続立会末及び立会内約定の独立補足.json'
    source_path=HERE/'独立配分の同数量単独と全31源別注文及び全原板時価の完全一致.json'
    boundary,source=read(boundary_path),read(source_path)
    assert boundary['全合格'] and boundary['口座数']==3286 and boundary['全注文数']==11320
    assert boundary['立会末以降約定']==boundary['連続立会末以降約定']==boundary['立会開始以前約定']==0
    assert boundary['運用区切り以降約定']==23 and len(boundary['具体例'])==23
    assert source['全合格'] and len(source['検査'])==124
    hashes(boundary['SHA256']);hashes(source['SHA256'])
    hashes(fixed['SHA256'])
    extra_paths=[Path(__file__),evidence_path,proof_path,manifest_path,analysis_path,boundary_path,source_path,
                 fixed_path,HERE/'元full単純起動の中断と依存名補足.json',driver_path,full_path]
    bindings.update({str(path.relative_to(ROOT)):digest(path) for path in extra_paths})
    result=dict(全合格=True,正式全53最終合格=True,全31既知=True,新未見場数=0,
                正式証拠='新audit_parallelの全53同範囲再検算と元後段比較。中断した元fullを正証拠にしない。',
                中断した1674口座を流用=0,独立照合件数=dict(COUNT),全件数=dict(totals),
                口座数=3286,商品期間数=848,注文数=11320,決済親数=5660,全原板行数=419839871,
                元main26文の全構文及び再結合同一=True,全53チェックポイントSHA実一致=True,
                analysis全31全値及び全8期間と安定性一致=True,凍結181依存実一致=True,
                数学検算基準変更=0,凍結full変更=0,依存名補足='メタ指紋保存のstate_checks名のみ。',
                M82の同数量源単独124経路一致=True,境界='23件は保守cut以降の返済、連続末と立会末以降0。代理約定時計の検算。',
                限界='全31は既知。監査合格は実装・会計の一致で、収益目標達成や未見市場性能ではない。真の受信時計・実約定・全量気配約定を保証しない。',
                原本変更=0,現在API取得=0,実注文=0,SHA256=bindings)
    output=HERE/'全53並列再検算の全証跡とチェックポイント及び根の全値の独立最終受入.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('全53の正式独立最終受入合格。3286口座・848期間・11320注文・5660親。',flush=True)
    print('最終受入SHA256='+digest(output),flush=True)


if __name__=='__main__':main()
