"""登録済み売買器を変更せず、その読取と特徴処理だけを独立診断へ複写する。"""

from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    """金融処理を含まない原板特徴抽出器を作る。

    引数: なし。
    返り値: None。Portfolio生成・Observe・OnFillは生成コードへ含めない。
    """
    source = (HERE / 'engine_go/main.go').read_text(encoding='utf-8')
    header = source[source.index('package main'):source.index('type Scene struct')]
    header = header.replace('\n\t"errors"', '').replace('\n\t"path/filepath"', '').replace('\n\t"futurealgorithm/sessiontrader/internal/rules"', '')
    types = source[source.index('type Scene struct'):source.index('type StudyConfig struct')]
    types += source[source.index('type rawLevel struct'):source.index('type Event struct')]
    body = source[source.index('// readJSON'):source.index('// newPortfolio')]
    main_code = '''
// main は指定時間帯の特徴だけを書き出します。
//
// 引数: manifest/scene/from/to/outのCLI文字列。返り値: なし。売買状態は生成しません。
func main() {
 manifest:=flag.String("manifest","../data/原資料一覧149.json","原資料"); sceneName:=flag.String("scene","","場"); fromText:=flag.String("from","","開始");toText:=flag.String("to","","終了");output:=flag.String("out","特徴.jsonl","出力");flag.Parse()
 var input struct{Sessions []Scene `json:"sessions"`};if e:=readJSON(*manifest,&input);e!=nil{panic(e)}
 from,e:=stamp(*fromText);if e!=nil{panic(e)};to,e:=stamp(*toText);if e!=nil{panic(e)}
 var scene Scene;for _,s:=range input.Sessions{if s.Session==*sceneName{scene=s}}
 if scene.Session==""{panic("場がありません")};boards,_,e:=loadBoards(scene);if e!=nil{panic(e)};features,e:=newFeatures(scene,scene.Start);if e!=nil{panic(e)}
 file,e:=os.Create(*output);if e!=nil{panic(e)};defer file.Close();enc:=json.NewEncoder(file);count:=0
 for _,board:=range boards{if board.Time>=to{break};o,e:=features.OnBoard(board);if e!=nil{panic(e)};if board.Reference!="NK225"||board.Time<from{continue};if e=enc.Encode(o);e!=nil{panic(e)};count++}
 fmt.Println("特徴行",count,"金融再生0")
}
'''
    target = HERE / 'engine_inspect149'
    target.mkdir(exist_ok=True)
    code = header + types + body + main_code
    assert 'Portfolio' not in code and 'OnFill' not in code and '.Observe(' not in code
    (target / 'main.go').write_text(code, encoding='utf-8')
    (target / 'go.mod').write_text('module futurealgorithm/sessiontrader/inspect\n\ngo 1.24.0\n\nrequire futurealgorithm/sessiontrader v0.0.0\nreplace futurealgorithm/sessiontrader => ../engine_go\n', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
