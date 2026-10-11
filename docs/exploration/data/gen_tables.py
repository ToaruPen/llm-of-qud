import os, re, json, sys
S=sys.argv[1]
B=os.path.expanduser("~/Library/Application Support/Steam/steamapps/common/Caves of Qud/CoQ.app/Contents/Resources/Data/StreamingAssets/Base")
D=os.path.expanduser("~/Dev/coq-decompiled_stable")
# Keys enum
keys={}
for l in open(D+"/ConsoleLib.Console/Keys.cs"):
    m=re.match(r'\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+),',l)
    if m:
        v=int(m.group(2),0)
        keys.setdefault(v,m.group(1))
def dec(code):
    code=int(code); mods=[]
    for bit,name in ((0x40000,'Alt'),(0x20000,'Ctrl'),(0x10000,'Shift')):
        if code & bit: mods.append(name); code-=bit
    return '+'.join(mods+[keys.get(code,str(code))])
km=json.load(open(B+"/DefaultKeymap.json"))
legacy={}
for tbl,tag in (("PrimaryMapCommandToKeyLayer","P"),("SecondaryMapCommandToKeyLayer","S")):
    for d in km[tbl].values():
        for cmd,code in d.items():
            legacy.setdefault(cmd,[]).append(f"{tag}:{dec(code)}")
handlers={}
for l in open(S+"/handlers.txt"):
    k,v=l.rsplit(' ',1); handlers.setdefault(k,int(v))
X="XRLCore.cs"
modal={
 "CmdMoveTo":"セルピッカー PickTarget (XRLCore.cs:1237)",
 "CmdAttackDirection":"方向ピッカー PickDirection (XRLCore.cs:1393)",
 "CmdAttackCell":"セルピッカー (XRLCore.cs:1405)",
 "CmdMoveToPointOfInterest":"Popup.PickOption (XRLCore.cs:1347)",
 "CmdWaitMenu":"Popup.PickOption (XRLCore.cs:929)",
 "CmdMoveMenu":"Popup.PickOption (XRLCore.cs:967)",
 "CmdWaitN":"Popup.AskNumber (XRLCore.cs:1559)",
 "CmdSystemMenu":"システムメニュー popup (XRLCore.cs:983-1136)",
 "CmdLook":"Look モード Look.ShowLooker (XRLCore.cs:1697)",
 "CmdHelp":"Manual.ShowHelp (XRLCore.cs:1701)",
 "CmdJournal":"Screens.Show (XRLCore.cs:1706-1709)",
 "CmdTinkering":"Screens.Show (XRLCore.cs:1710-1713)",
 "CmdSave":"Yes/No popup, OptionAllowSaveLoad 必須 (XRLCore.cs:1784-1790)",
 "CmdLoad":"Yes/No popup, OptionAllowSaveLoad 必須 (XRLCore.cs:1792-1795)",
 "CmdQuit":"Yes/No popup (XRLCore.cs:1727-1729)",
 "CmdAbilities":"AbilityManager.Show (XRLCore.cs:1806-1818)",
 "CmdTarget":"PickTarget (XRLCore.cs:1826-1829)",
 "CmdThrow":"Combat.ThrowWeapon (XRLCore.cs:1837) — ターゲット選択 UI と推定",
 "CmdFire":"ミサイル照準 UI (XRLCore.cs:1840-) — Targeting layer",
 "CmdWish":"WishManager.AskWish 文字列入力 (XRLCore.cs:1883-1885)",
 "CmdWishMenu":"WishMenu.OpenWishMenu (XRLCore.cs:1886-1888)",
 "CmdFactions":"Screens.ShowPopup (XRLCore.cs:1889-1891)",
 "CmdQuests":"Screens.Show (XRLCore.cs:1892-1895)",
 "CmdActiveEffects":"ShowActiveEffects (XRLCore.cs:1896-1898)",
 "CmdLastStatusPage":"Screens.Show (XRLCore.cs:1899-1901)",
 "CmdCharacter":"Screens.Show (XRLCore.cs:1902-1905)",
 "CmdInventory":"Screens.Show (XRLCore.cs:1906-1910)",
 "CmdEquipment":"Screens.Show (XRLCore.cs:1911-1915)",
 "CmdSkillsPowers":"Screens.Show (XRLCore.cs:1916-1919)",
 "CmdAutoExplore":"非モーダル: AutoAct.Setting=\"?\" (XRLCore.cs:1920-1926)",
 "CmdAutoAttack":"非モーダル: AutoAct.Setting=\"a\"、target 無しは popup (XRLCore.cs:1927-1940)",
 "CmdWalk":"方向ピッカー (XRLCore.cs:2105-2110)",
 "CmdGet":"FireEvent CommandGet (XRLCore.cs:2144) — 複数物品時リスト popup と推定",
 "CmdGetFrom":"FireEvent CommandGetFrom (XRLCore.cs:2147) — 方向/対象選択と推定",
 "CmdOpen":"方向ピッカー (XRLCore.cs:2174-2176)",
 "CmdTalk":"方向ピッカー→会話 UI (XRLCore.cs:2212-2238)",
 "CmdMessageHistory":"Messages.Show (XRLCore.cs:2296-2298)",
 "CmdCompanions":"Popup.PickGameObject (XRLCore.cs:2299-2321)",
 "CmdUse":"PerformSmartUse (XRLCore.cs:1679) — 文脈 popup と推定",
 "CmdReload":"CommandReloadEvent (XRLCore.cs:2206)",
 "CmdReplaceCell":"CommandReplaceCellEvent (XRLCore.cs:2209) — セル選択 popup と推定",
 "CmdToggleMessageVerbosity":"非モーダル: Messages.Terse 切替 (XRLCore.cs:2240-2250)",
 "CmdShowSidebar":"非モーダル (XRLCore.cs:2251)",
 "CmdShowSidebarMessages":"非モーダル (XRLCore.cs:2254)",
}
for d in ["N","S","E","W","NE","NW","SE","SW"]:
    if "CmdMove"+d in handlers: modal["CmdMove"+d]=f"非モーダル: Player.Move (XRLCore.cs:{handlers['CmdMove'+d]})"
    modal["CmdAttack"+d]=f"非モーダル (XRLCore.cs:{handlers.get('CmdAttack'+d,'?')})"
for c in ["CmdMoveU","CmdMoveD","CmdAttackU","CmdAttackD","CmdWait","CmdWait20","CmdWait100","CmdWaitUntilHealed","CmdWaitUntilPartyHealed","CmdWaitUntilMorning","CmdAttackNearest","CmdExplore","CmdXP","CmdNoclipU","CmdNoclipD","CmdDismemberLimb","CmdRegenerateLimb","CmdShowFPS","CmdShowReachability","CmdToggleAnimation"]:
    if c in handlers: modal.setdefault(c,f"非モーダル/即時 (XRLCore.cs:{handlers[c]})")
for c in ["CmdMoveFarNW","CmdMoveFarN","CmdMoveFarNE","CmdMoveFarW","CmdMoveFarE","CmdMoveFarSW","CmdMoveFarS","CmdMoveFarSE","CmdMoveCenter"]:
    modal[c]="非モーダル: 自動移動 (XRLCore.cs:1270-1325)"
for i in range(1,11): modal[f"CmdAbility{i}"]="Modern UI 専用: AbilityBar ホットキー→TrySendCommandEventOnPlayer (GameManager.cs:2389-2395)"
for i in range(1,6): modal[f"CmdAbilityBar{i}"]="Modern UI 専用: AbilityBar ページ切替, CurrentGameView==Stage (GameManager.cs:2398-2418)"
for c in ["Ability Page Up","Ability Page Down"]: modal[c]="注意: GameManager は CmdAbilityNextPage/PrevPage を参照 (GameManager.cs:2420-2426) — ID 不一致"
for c in ["CmdZoomIn","CmdZoomOut","CmdShowBrainlog"]: modal[c]=f"XRLCore では no-op 分岐 (XRLCore.cs:{handlers.get(c)})"

def esc(s): return s.replace('|','\\|')
rows=[]
for l in open(S+"/cmds.txt"):
    ln,cid,disp,cat,layer,kb,extra=l.rstrip('\n').split('|',6)
    auto=''
    m=re.search(r"'Auto': '(\w+)'",extra); 
    if m: auto=m.group(1)
    note=modal.get(cid,'')
    if not note:
        if layer in("UINav","Menus","CategoryNav","StatusScreens","StatusScreens:Charsheet","Trade","Targeting","Chargen","Conversation"):
            note=f"モーダル内でのみ有効 (Layer={layer} から推定)"
        elif cid in handlers: note=f"XRLCore.cs:{handlers[cid]}"
    rows.append((int(ln),cid,disp,cat,layer,kb,' '.join(legacy.get(cid,[])),auto,note))
out=["| Commands.xml 行 | ID | 表示名 | Category | Layer | 既定キー (Commands.xml) | 旧 DefaultKeymap.json | Auto | モーダル性 / ハンドラ |","|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    out.append("| "+" | ".join(esc(str(x)) for x in r)+" |")
open(S+"/cmd_table.md","w").write("\n".join(out)+"\n")
# options full table
o=["| Options.xml 行 | ID | 表示名 | Category | Type | Default | 追加属性 |","|---|---|---|---|---|---|---|"]
for l in open(S+"/opts.txt"):
    ln,oid,disp,cat,typ,dflt,extra=l.rstrip('\n').split('|',6)
    extra=extra.replace("{","").replace("}","").replace("'","")
    o.append("| "+" | ".join(esc(x) for x in (ln,oid,disp,cat,typ,dflt,extra))+" |")
open(S+"/opt_table.md","w").write("\n".join(o)+"\n")
# hidden handlers not in Commands.xml
ids={r[1] for r in rows}
hid=[(k,v) for k,v in sorted(handlers.items(), key=lambda x:x[1]) if k.startswith("Cmd") and k not in ids]
open(S+"/hidden.md","w").write("\n".join(f"| `{k}` | XRLCore.cs:{v} |" for k,v in hid)+"\n")
# legacy keymap commands not in Commands.xml
print("legacy-only:", [c for c in legacy if c not in ids])
print("rows",len(rows),"hidden",len(hid))
