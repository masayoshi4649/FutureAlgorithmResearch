package main

import (
 "crypto/sha256"
 "encoding/hex"
 "encoding/json"
 "errors"
 "flag"
 "fmt"
 "futurealgorithm/sessiontrader/internal/rules"
 "io"
 "os"
 "path/filepath"
 "reflect"
 "sort"
 "strings"
 "sync"
 "time"
)

type Fingerprint163 struct {Path string `json:"path"`; SHA string `json:"sha256"`}
type Stage163 struct {Stage string `json:"stage"`; ManifestSHA string `json:"manifest_sha256"`; SpecSHA string `json:"spec_sha256"`; ConfigsSHA string `json:"configs_sha256"`; FreezeSHA string `json:"freeze_sha256,omitempty"`; Selected map[string]string `json:"selected,omitempty"`}
type ResultFile163 struct {Session string `json:"session"`; Path string `json:"path"`; SHA string `json:"sha256"`; Cases int `json:"cases"`}
type Proof163 struct {Completed bool `json:"completed"`; Returncode int `json:"returncode"`; Stage Stage163 `json:"stage"`; Sessions int `json:"sessions"`; Cases int `json:"cases"`; SourcesUnchanged bool `json:"sources_unchanged"`; Sources map[string]string `json:"sources"`; Results []ResultFile163 `json:"results"`; Started string `json:"started_at"`; Finished string `json:"finished_at"`}

// hash163 はファイルを逐次読み、内容のSHA256を返します。
//
// 引数: path(string)。返り値: stringとerror。原資料の内容を変更しません。
func hash163(path string)(string,error){f,e:=os.Open(path);if e!=nil{return "",e};defer f.Close();h:=sha256.New();if _,e=io.Copy(h,f);e!=nil{return "",e};return hex.EncodeToString(h.Sum(nil)),nil}

// verifyHashes163 は登録時の全実装・定義が現在も同じ内容か検査します。
//
// 引数: sources(map[string]string)。返り値: error。不足又は不一致で停止します。
func verifyHashes163(sources map[string]string)error{for path,expected:=range sources{got,e:=hash163(path);if e!=nil{return e};if got!=expected{return fmt.Errorf("登録指紋差:%s",path)}};return nil}

// requireStage163 は登録と実行段階、後半の事前選択凍結を確認します。
//
// 引数: root/permission/manifest/spec/configs/stage/freeze(string)。返り値: Stage163、指紋map、error。
func requireStage163(root,permission,manifest,spec,configs,stage,freeze string)(Stage163,map[string]string,error){
 v:=Stage163{Stage:stage};sources:=map[string]string{}
 if stage!="train_validation"&&stage!="locked_test"{return v,sources,errors.New("段階はtrain_validation又はlocked_testです")}
 var permit struct{Registered bool;Returncode *int;Allowed []string `json:"allowed_stages"`;ManifestSHA string `json:"manifest_sha256"`;SpecSHA string `json:"spec_sha256"`;ConfigsSHA string `json:"configs_sha256"`;FreezeSHA string `json:"freeze_sha256"`;Registration Fingerprint163}
 if permission==""{return v,sources,errors.New("登録後の段階許可が必要です")}
 if e:=readJSON(permission,&permit);e!=nil{return v,sources,e}
 if !permit.Registered||permit.Returncode==nil||*permit.Returncode!=0{return v,sources,errors.New("登録成功の明示なし")}
 allowed:=false;for _,s:=range permit.Allowed{if s==stage{allowed=true}}
 if !allowed{return v,sources,errors.New("未許可の段階")}
 for _,x:=range []struct{path,expected string;out *string}{{manifest,permit.ManifestSHA,&v.ManifestSHA},{spec,permit.SpecSHA,&v.SpecSHA},{configs,permit.ConfigsSHA,&v.ConfigsSHA}}{h,e:=hash163(x.path);if e!=nil{return v,sources,e};if h!=x.expected{return v,sources,errors.New("段階許可の定義指紋不一致")};*x.out=h;sources[x.path]=h}
 receiptPath:=filepath.Join(root,filepath.FromSlash(permit.Registration.Path));h,e:=hash163(receiptPath);if e!=nil{return v,sources,e};if h!=permit.Registration.SHA||permit.Registration.Path==""{return v,sources,errors.New("登録受領の指紋差")}
 var receipt struct{Registered bool;Returncode *int;Sources []Fingerprint163}
 if e=readJSON(receiptPath,&receipt);e!=nil{return v,sources,e};if !receipt.Registered||receipt.Returncode==nil||*receipt.Returncode!=0||len(receipt.Sources)==0{return v,sources,errors.New("登録受領に成功と源がありません")}
 for _,x:=range receipt.Sources{sources[filepath.Join(root,filepath.FromSlash(x.Path))]=x.SHA}
 sources[receiptPath]=h;h,e=hash163(permission);if e!=nil{return v,sources,e};sources[permission]=h
 if stage=="locked_test"{
  if freeze==""{return v,sources,errors.New("後半には事前選択凍結が必要です")};h,e=hash163(freeze);if e!=nil{return v,sources,e};if h!=permit.FreezeSHA{return v,sources,errors.New("選択凍結指紋差")}
  var f struct{TestOpened *bool `json:"test_opened"`;Selected map[string]string `json:"selected"`;ManifestSHA string `json:"manifest_sha256"`;SpecSHA string `json:"spec_sha256"`;ConfigsSHA string `json:"configs_sha256"`;Sessions int `json:"selection_sessions"`}
  if e=readJSON(freeze,&f);e!=nil{return v,sources,e};if f.TestOpened==nil||*f.TestOpened||f.Sessions!=40||len(f.Selected)!=2||f.ManifestSHA!=v.ManifestSHA||f.SpecSHA!=v.SpecSHA||f.ConfigsSHA!=v.ConfigsSHA{return v,sources,errors.New("未開封選択の定義不整合")}
  permitted:=map[string]bool{};for _,c:=range configs163()[2:]{permitted[c.ID]=true};for _,kind:=range []string{"Day","Night"}{if !permitted[f.Selected[kind]]{return v,sources,errors.New("昼夜固定選択不正")}}
  v.FreezeSHA=h;v.Selected=f.Selected;sources[freeze]=h
 }
 return v,sources,verifyHashes163(sources)
}

// execute163 は場間だけ並列化し、各場の原行順と十条件共通入力を維持します。
//
// 引数: scenes([]Scene)、configs([]Policy163)、sets、out(string)、workers(int)。返り値: 結果指紋列とerror。
func execute163(scenes []Scene,configs []Policy163,sets map[string]map[string]string,out string,workers int)([]ResultFile163,error){
 if workers<1||workers>8{return nil,errors.New("並列数は1〜8です")};if e:=os.MkdirAll(out,0700);e!=nil{return nil,e}
 for _,s:=range scenes{if _,e:=os.Stat(filepath.Join(out,s.Session+".json"));!os.IsNotExist(e){return nil,errors.New("既存結果を上書きしません")}}
 type done struct{file ResultFile163;err error};jobs:=make(chan Scene);completed:=make(chan done,len(scenes));var wg sync.WaitGroup
 for i:=0;i<workers;i++{wg.Add(1);go func(){defer wg.Done();for s:=range jobs{started:=time.Now();result,e:=run163(s,configs,sets);path,_:=filepath.Abs(filepath.Join(out,s.Session+".json"));if e==nil{e=save159(path,result)};h:="";if e==nil{h,e=hash163(path)};completed<-done{ResultFile163{Session:s.Session,Path:path,SHA:h,Cases:len(result.Cases)},e};if e==nil{fmt.Printf("完了 %s 10条件 %s\n",s.Session,time.Since(started).Round(time.Millisecond))}}}()}
 for _,s:=range scenes{jobs<-s};close(jobs);wg.Wait();close(completed)
 results:=[]ResultFile163{};errs:=[]error{};for d:=range completed{if d.err!=nil{errs=append(errs,fmt.Errorf("%s:%w",d.file.Session,d.err))}else{results=append(results,d.file)}}
 sort.Slice(results,func(i,j int)bool{return results[i].Session<results[j].Session});return results,errors.Join(errs...)
}

// rules163 は固定コピーの三つの元手法規則を読みます。
//
// 引数: folder(string)。返り値: 規則mapとerror。元アプリの現在値へ動的接続しません。
func rules163(folder string)(map[string]map[string]string,error){sets:=map[string]map[string]string{};for _,m:=range []string{"S01","P05","D07"}{s,e:=rules.LoadFor(filepath.Join(folder,"NK225_"+m+".toml"),strings.ToLower(m));if e!=nil{return nil,e};sets[m]=s.Expressions()};return sets,nil}

// main は候補出力だけを登録前に許し、金融処理には段階許可を必須にします。
//
// 引数: CLI。返り値: なし。全場正常完了と指紋一致後だけ完了証跡を保存します。
func main(){
 manifest:=flag.String("manifest","../inputs163.json","固定53場目録");configs:=flag.String("configs","configs163.json","固定十条件");spec:=flag.String("spec","../計画163.md","登録仕様");permission:=flag.String("registration","","段階許可");stage:=flag.String("stage","","前40又は後13");freeze:=flag.String("freeze","","後半の固定選択");out:=flag.String("out","","段階結果保存先");workers:=flag.Int("workers",8,"場独立並列");export:=flag.String("export-configs","","非金融の条件出力");flag.Parse()
 fail:=func(e error){fmt.Fprintln(os.Stderr,e);os.Exit(1)}
 if *export!=""{if e:=save159(*export,configs163());e!=nil{fail(e)};return}
 root,e:=filepath.Abs("../../..");if e!=nil{fail(e)}
 stageProof,sources,e:=requireStage163(root,*permission,*manifest,*spec,*configs,*stage,*freeze);if e!=nil{fail(e)}
 var configured []Policy163;if e=readJSON(*configs,&configured);e!=nil{fail(e)};if !reflect.DeepEqual(configured,configs163()){fail(errors.New("登録した十条件以外は実行できません"))}
 var input struct{Sessions []Scene};if e=readJSON(*manifest,&input);e!=nil{fail(e)};if len(input.Sessions)!=53{fail(errors.New("53場目録ではありません"))}
 scenes:=[]Scene{};counts:=map[string]int{};seen:=map[string]bool{}
 for _,s:=range input.Sessions{if seen[s.Session]||s.Partial||(s.Kind!="Day"&&s.Kind!="Night"){fail(errors.New("対象場の重複又は不正"))};seen[s.Session]=true;counts[s.Split]++;if (*stage=="train_validation"&&(s.Split=="train"||s.Split=="validation"))||(*stage=="locked_test"&&s.Split=="test"){scenes=append(scenes,s)}}
 if counts["train"]!=30||counts["validation"]!=10||counts["test"]!=13{fail(errors.New("時系列分割不一致"))}
 if *out==""{*out=filepath.Join("../results",*stage)};proofPath:=filepath.Join(*out,"再生完了163_"+*stage+".json");if _,e=os.Stat(proofPath);!os.IsNotExist(e){fail(errors.New("既存完了証跡あり"))}
 sets,e:=rules163("rules");if e!=nil{fail(e)};started:=time.Now().Format(time.RFC3339Nano)
 results,e:=execute163(scenes,configured,sets,*out,*workers);if e!=nil{fail(e)};if e=verifyHashes163(sources);e!=nil{fail(e)}
 proof:=Proof163{Completed:true,Returncode:0,Stage:stageProof,Sessions:len(results),Cases:len(results)*10,SourcesUnchanged:true,Sources:sources,Results:results,Started:started,Finished:time.Now().Format(time.RFC3339Nano)}
 if e=save159(proofPath,proof);e!=nil{fail(e)}
 // 金融結果と異なり、完了情報だけを標準出力へ示します。
 raw,_:=json.Marshal(map[string]any{"完了":true,"場数":len(results),"条件場数":len(results)*10,"証跡":proofPath});fmt.Println(string(raw))
}
