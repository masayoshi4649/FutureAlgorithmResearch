"""市場結果を読まず、全41行の選択表示を明示した人工会計で確認する。"""

from datetime import date,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path

import render124 as R


def method_specs(path: Path,name: str) -> list[dict]:
    """
    機能: 源の条件名だけを取得する。
    引数: path(Path)、name(str)は条件定義sourceとmodule名。
    返り値: list[dict]は固定条件。金融本文を使用しない。
    """
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.specifications()


def row(scene: str,symbol: str,method: str,index: int) -> dict:
    """
    機能: 実測と関係しない表示専用の人工会計一行を作る。
    引数: scene/symbol/method(str)、index(int)は表示識別子と人工添字。
    返り値: dictは手数料後利益・損失等を含む人工行。
    """
    active=index%5!=0;profit=float(1000+index*30) if active else 0.
    loss=float(800+index*10) if active and index%3==0 else 0.
    return dict(session=scene,symbol=symbol,method=method,profit=profit,loss=loss,net=profit-loss,
        wins=int(active),losses=int(active and loss>0),entries=int(active)+int(active and loss>0),
        fees=82.*(int(active)+int(active and loss>0)),unclosed=0,origin='人工表示確認',
        option_known=index<11,option_effective_changed=index<8 and method not in ('O00','O10','O11'))


def main() -> None:
    """
    機能: 人工984+82+779表示行を作り、正式公開先とは別に描画検査用HTMLを保存する。
    引数: なし。
    返り値: None。市場・保存金融・価格配列・API・登録・正式HTMLの変更は0。
    """
    specs=method_specs(R.HERE.parent/'grid/catalog124.py','artificial_report_catalog')
    gaps=method_specs(R.HERE.parent/'grid/catalog123.py','artificial_report_gaps')
    day=date(2026,9,21);scenes=[]
    while day<=date(2026,10,19):
        if day.weekday()<5:
            scenes.append(day.isoformat()+'_Day')
            if day<date(2026,10,19):scenes.append(day.isoformat()+'_Night')
        day+=timedelta(days=1)
    assert len(scenes)==41
    grid=dict(sessions=scenes,specs=specs,
        rows=[row(scene,symbol,spec['id'],i) for symbol in ('TOPIX','NK225') for spec in specs for i,scene in enumerate(scenes)],
        latest_rows=[row(scenes[-1],'TOPIX',spec['id'],40) for spec in gaps])
    old_grid=dict(sessions=scenes[:-1],specs=gaps,
        runs=[row(scene,'TOPIX',spec['id'],i) for spec in gaps if spec['id']!='I3_G3' for i,scene in enumerate(scenes[:-1])],
        baseline=dict(rows=[row(scene,'TOPIX','HOLD_CLOSE_6M',i) for i,scene in enumerate(scenes[:-1])]))
    old_e01=dict(sessions=scenes[:-1],rows=[])
    e01=dict(rows=[])
    for symbol in ('TOPIX','NK225'):
        for i,scene in enumerate(scenes):
            source=row(scene,symbol,'E01',i)
            source['winning_lots']=source.pop('wins');source['losing_lots']=source.pop('losses')
            source.pop('entries')
            if i<33:source['unclosed']=None;source['verified_flat']=True
            (old_e01['rows'] if i<40 else e01['rows']).append(source)
    data=R.prepare(grid,e01,old_grid,old_e01);data['synthetic']=True
    assert len(data['rows'])==1066 and len(data['gap_rows'])==779
    assert sum(r['unclosed'] is None for r in data['rows'])==66
    folder=R.HERE/'artificial';folder.mkdir(exist_ok=True)
    content=R.render(data)
    probe=r'''<script>
let checks=0;const results=[];
/**
 * 人工表示が予定値と一致するかを記録する。
 * @param {boolean} condition - 照合条件。
 * @param {string} name - 確認内容。
 * @returns {undefined} 不一致は即時停止する。
 */
function check(condition,name){if(!condition)throw Error(name);checks++;}
check(document.body.dataset.ready==='true','描画完了');
check(document.querySelectorAll('#latest-body tr').length===5,'追加五行');
for(const symbol of ['TOPIX','NK225']){
 document.getElementById('summary-symbol').value=symbol;renderSummary();
 check(document.querySelectorAll('#summary-body tr').length===12,'十二条件一覧');
 for(const method of ['E01',...data.specs.map(s=>s.id)]){
  document.getElementById('session-symbol').value=symbol;document.getElementById('session-method').value=method;renderSessions();
  check(document.querySelectorAll('#session-body tr').length===41,'全41行');
  check(document.querySelectorAll('#session-body tr.new').length===1,'新一場区別');
  const own=data.rows.filter(r=>r.symbol===symbol&&r.method===method),s=stats(own);
  check(document.querySelector('#session-total td:nth-child(4)').textContent===number(s.net,true),'収支合計');
  check(document.querySelector('#session-total td:nth-child(5)').textContent===number(s.wins),'勝ち枚数合計');
  check(document.querySelectorAll('#split-body tr').length===(method==='E01'?2:4),'旧新既知不明区分');
 }
}
for(const spec of data.gap_specs){document.getElementById('gap-method').value=spec.id;renderGaps();check(document.querySelectorAll('#gap-body tr').length===41,'旧十九全41行');}
document.getElementById('session-symbol').value='TOPIX';document.getElementById('session-method').value='O00';renderSessions();
document.getElementById('summary-symbol').value='TOPIX';renderSummary();document.getElementById('gap-method').value='I3_G3';renderGaps();
check(document.documentElement.scrollWidth<=window.innerWidth,'文書横はみ出しなし');
const pre=document.createElement('pre');pre.id='artificial-proof';pre.textContent=JSON.stringify({passed:true,checks,financial_replay:0,market_reads:0});document.body.append(pre);
</script>'''
    content=content.replace('</body>',probe+'</body>')
    target=folder/'人工会計だけの表示確認.html';assert not target.exists()
    target.write_text(content,encoding='utf8')
    print(json.dumps(dict(path=target.relative_to(R.ROOT).as_posix(),sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        financial_reads=0,financial_replay=0),ensure_ascii=False))


if __name__=='__main__':
    main()
