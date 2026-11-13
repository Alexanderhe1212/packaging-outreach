import Cocoa
import WebKit
final class App:NSObject,NSApplicationDelegate,WKScriptMessageHandler,WKNavigationDelegate {
 var pages:[String:WKWebView]=[:];var window:NSWindow!;var web:WKWebView!;var busy=false;var polling=false;var ready=false
 let root=(Bundle.main.resourceURL?.appendingPathComponent("Workspace").path ?? NSHomeDirectory()+"/Library/Application Support/UserRadar/desktop")+"/"
 let version=Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "unknown"
 func configuration()->WKWebViewConfiguration {
  let config=WKWebViewConfiguration()
  let language=UserDefaults.standard.string(forKey:"uiLanguage")=="zh" ? "zh" : "en"
  let script=(try? String(contentsOfFile:root+"i18n.js",encoding:.utf8)) ?? ""
  config.userContentController.addUserScript(WKUserScript(source:"window.__radarTheme='"+(UserDefaults.standard.string(forKey:"uiTheme") ?? "green")+"';window.__radarLang='"+language+"';"+script,injectionTime:.atDocumentEnd,forMainFrameOnly:true))
  return config
 }
 func applicationDidFinishLaunching(_ notification:Notification){
  let config=configuration();config.userContentController.add(self,name:"desktop")
  web=WKWebView(frame:.zero,configuration:config);web.navigationDelegate=self
  window=NSWindow(contentRect:NSRect(x:0,y:0,width:1100,height:800),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
  window.isReleasedWhenClosed=false // The app keeps this window for Dock/Finder reopen.
  window.title="User Radar \(version) — Outreach Workspace";window.minSize=NSSize(width:1000,height:650);window.contentView=web
  updateLanguageChrome()
  window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
  web.loadFileURL(URL(fileURLWithPath:root+"dashboard.html"),allowingReadAccessTo:URL(fileURLWithPath:root))
 }
 func updateLanguageChrome(){
  let zh=UserDefaults.standard.string(forKey:"uiLanguage")=="zh"
  window.title="User Radar \(version) — "+(zh ? "客户开发工作台" : "Outreach Workspace")
  let menu=NSMenu();let item=NSMenuItem();menu.addItem(item);let sub=NSMenu();item.submenu=sub
  sub.addItem(withTitle:zh ? "关于 User Radar" : "About User Radar",action:#selector(NSApplication.orderFrontStandardAboutPanel(_:)),keyEquivalent:"")
  sub.addItem(withTitle:zh ? "刷新" : "Refresh",action:#selector(refresh),keyEquivalent:"r")
  sub.addItem(NSMenuItem.separator())
  sub.addItem(withTitle:zh ? "退出 User Radar（后台继续运行）" : "Quit User Radar (background continues)",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
  NSApp.mainMenu=menu
 }
 @objc func refresh(){
  if let page=pages.values.first(where:{!$0.isHidden}){page.reloadFromOrigin()}else{web.reloadFromOrigin()}
 }
 func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!){
  let log=NSHomeDirectory()+"/Library/Application Support/UserRadar/desktop/load-debug.txt"
  try? ("version="+version+"\n"+(webView.url?.absoluteString ?? "nil")).write(toFile:log,atomically:true,encoding:.utf8)
  let lang=UserDefaults.standard.string(forKey:"uiLanguage")=="zh" ? "zh" : "en"
  webView.evaluateJavaScript("window.UserRadarI18n?.setLanguage('"+lang+"');window.ExhibitorReview?.setLanguage('"+lang+"')",completionHandler:nil)
  if !ready {ready=true;run("boot")}
 }
 func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage){
  // Only our local top-level dashboard can control the real accounts.
  guard message.webView === web,message.frameInfo.isMainFrame,web.url?.standardizedFileURL==URL(fileURLWithPath:root+"dashboard.html").standardizedFileURL,let action=message.body as? String else{return}
  if action.hasPrefix("theme:") {
   let value=String(action.dropFirst(6));guard ["green","blue","violet"].contains(value) else{return}
   UserDefaults.standard.set(value,forKey:"uiTheme")
   for page in [web!] + Array(pages.values) {page.evaluateJavaScript("window.setRadarTheme?.('"+value+"')",completionHandler:nil)}
   return
  }
  if action.hasPrefix("language:") {
   let language=action=="language:zh" ? "zh" : "en"
   UserDefaults.standard.set(language,forKey:"uiLanguage")
   updateLanguageChrome()
   for page in [web!] + Array(pages.values) {page.evaluateJavaScript("window.UserRadarI18n?.setLanguage('"+language+"');window.ExhibitorReview?.setLanguage('"+language+"')",completionHandler:nil)}
   return
  }
  if action.hasPrefix("tab:"){showTab(String(action.dropFirst(4)));return}
  guard ["snapshot","start","pause","boot"].contains(action) else{return}
  run(action)
 }
 func showTab(_ tab:String){

  for p in pages.values {p.isHidden=true}
  let urls=["expansion":"http://127.0.0.1:18800/expansion","funnel":"http://127.0.0.1:18800/funnel","settings":"http://127.0.0.1:18800/?view=settings","writing":"http://127.0.0.1:18800/?view=compact&stage=writing&status=queued,researching,writing,ready","images":"http://127.0.0.1:18800/?view=compact&stage=images&status=imaging,ready","problems":"http://127.0.0.1:18800/problems","replies":"http://127.0.0.1:18800/?status=replied","customers":"http://127.0.0.1:18800/radar","mail":"http://127.0.0.1:18800/?view=compact","search":"http://127.0.0.1:18830/"]
  guard let url=urls[tab] else{return}
  if let p=pages[tab]{p.isHidden=false;if tab=="search" && p.url?.path != "/" {p.load(URLRequest(url:URL(string:url)!))};return}
  let p=WKWebView(frame:.zero,configuration:configuration());p.navigationDelegate=self;p.translatesAutoresizingMaskIntoConstraints=false;web.addSubview(p)
  NSLayoutConstraint.activate([p.leadingAnchor.constraint(equalTo:web.leadingAnchor,constant:206),p.trailingAnchor.constraint(equalTo:web.trailingAnchor),p.topAnchor.constraint(equalTo:web.topAnchor,constant:83),p.bottomAnchor.constraint(equalTo:web.bottomAnchor)])
  pages[tab]=p;p.load(URLRequest(url:URL(string:url)!))
 }
 func run(_ action:String){
  if action=="snapshot" {if polling || busy{return};polling=true}
  else {if busy{return};busy=true}
  DispatchQueue.global(qos:.userInitiated).async {
   let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/bin/python3");p.arguments=[self.root+"controller.py",action]
   let output=Pipe();p.standardOutput=output;p.standardError=FileHandle.nullDevice
   var data=Data()
   do {try p.run();data=output.fileHandleForReading.readDataToEndOfFile();p.waitUntilExit()}
   catch {data=try! JSONSerialization.data(withJSONObject:["ok":false,"error":"无法启动后台，请重试"])}
   let encoded=data.base64EncodedString()
   DispatchQueue.main.async{
    if action=="snapshot" {self.polling=false;if self.busy{return}}else{self.busy=false}
    self.web.evaluateJavaScript("receive(JSON.parse(decodeURIComponent(escape(atob('\(encoded)')))))",completionHandler:nil)
   }
  }
 }
 func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
  guard let url=action.request.url else{decisionHandler(.cancel);return}
  if url.isFileURL && url.standardizedFileURL==URL(fileURLWithPath:root+"dashboard.html").standardizedFileURL {decisionHandler(.allow);return}
  if url.host=="127.0.0.1" && url.path.hasPrefix("/benchmark") {decisionHandler(.cancel);NSWorkspace.shared.open(url);return}
  if url.host=="127.0.0.1" && [18800,18830].contains(url.port ?? 0) && webView !== self.web {decisionHandler(.allow);return}
  decisionHandler(.cancel)
  if ["http","https","mailto"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}
 }
 func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows:Bool)->Bool{window.makeKeyAndOrderFront(nil);return true}
}
let app=NSApplication.shared;let delegate=App();app.delegate=delegate;app.setActivationPolicy(.regular);app.run()
