import Cocoa
import WebKit
final class App:NSObject,NSApplicationDelegate,WKScriptMessageHandler,WKNavigationDelegate {
 var pages:[String:WKWebView]=[:];var window:NSWindow!;var web:WKWebView!;var busy=false;var polling=false;var ready=false
 let root=NSHomeDirectory()+"/Library/Application Support/UserRadar/desktop/"
 func configuration()->WKWebViewConfiguration {
  let config=WKWebViewConfiguration()
  let language=UserDefaults.standard.string(forKey:"uiLanguage")=="zh" ? "zh" : "en"
  let script=(try? String(contentsOfFile:root+"i18n.js",encoding:.utf8)) ?? ""
  config.userContentController.addUserScript(WKUserScript(source:"window.__radarLang='"+language+"';"+script,injectionTime:.atDocumentEnd,forMainFrameOnly:true))
  return config
 }
 func applicationDidFinishLaunching(_ notification:Notification){
  let config=configuration();config.userContentController.add(self,name:"desktop")
  web=WKWebView(frame:.zero,configuration:config);web.navigationDelegate=self
  window=NSWindow(contentRect:NSRect(x:0,y:0,width:1100,height:800),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
  window.title="User Radar — Outreach Workspace";window.minSize=NSSize(width:1000,height:650);window.contentView=web
  let menu=NSMenu();let item=NSMenuItem();menu.addItem(item);let sub=NSMenu();item.submenu=sub;sub.addItem(withTitle:"Quit User Radar (background continues)",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q");NSApp.mainMenu=menu
  window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
  web.loadFileURL(URL(fileURLWithPath:root+"dashboard.html"),allowingReadAccessTo:URL(fileURLWithPath:root))
 }
 func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!){try? (webView.url?.absoluteString ?? "nil").write(toFile:root+"load-debug.txt",atomically:true,encoding:.utf8);if !ready {ready=true;run("boot")}}
 func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage){
  // Only our local top-level dashboard can control the real accounts.
  guard message.webView === web,message.frameInfo.isMainFrame,web.url?.standardizedFileURL==URL(fileURLWithPath:root+"dashboard.html").standardizedFileURL,let action=message.body as? String else{return}
  if action.hasPrefix("language:") {
   let language=action=="language:zh" ? "zh" : "en"
   UserDefaults.standard.set(language,forKey:"uiLanguage")
   for page in [web!] + Array(pages.values) {page.evaluateJavaScript("window.UserRadarI18n?.setLanguage('"+language+"')",completionHandler:nil)}
   return
  }
  if action.hasPrefix("tab:"){showTab(String(action.dropFirst(4)));return}
  guard ["snapshot","start","pause","boot"].contains(action) else{return}
  run(action)
 }
 func showTab(_ tab:String){

  for p in pages.values {p.isHidden=true}
  let urls=["writing":"http://127.0.0.1:18800/?view=compact&stage=writing&status=queued,researching,writing,ready","images":"http://127.0.0.1:18800/?view=compact&stage=images&status=imaging,ready","problems":"http://127.0.0.1:18800/problems","replies":"http://127.0.0.1:18800/?status=replied","customers":"http://127.0.0.1:18800/radar","mail":"http://127.0.0.1:18800/?view=compact","search":"http://127.0.0.1:18830/"]
  guard let url=urls[tab] else{return}
  if let p=pages[tab]{p.isHidden=false;return}
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
  if url.host=="127.0.0.1" && [18800,18830].contains(url.port ?? 0) && webView !== self.web {decisionHandler(.allow);return}
  decisionHandler(.cancel)
  if ["http","https","mailto"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}
 }
 func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows:Bool)->Bool{window.makeKeyAndOrderFront(nil);return true}
}
let app=NSApplication.shared;let delegate=App();app.delegate=delegate;app.setActivationPolicy(.regular);app.run()
