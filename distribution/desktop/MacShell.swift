import Cocoa
import WebKit
final class Shell:NSObject,NSApplicationDelegate,WKNavigationDelegate {
 var window:NSWindow!;var web:WKWebView!;var child:Process!;var timer:Timer?;var attempts=0;var ready=false;var pipe:Pipe!
 let smoke=CommandLine.arguments.contains("--smoke-test")
 func applicationDidFinishLaunching(_ note:Notification){
  child=Process();child.executableURL=Bundle.main.resourceURL!.appendingPathComponent("runtime/UserRadar/UserRadar");child.arguments=["--serve-only"]
  pipe=Pipe();child.standardOutput=pipe
  pipe.fileHandleForReading.readabilityHandler={[weak self] handle in
   let data=handle.availableData
   if data.isEmpty{return}
   if String(data:data,encoding:.utf8)?.contains("USER_RADAR_READY")==true {DispatchQueue.main.async{guard let self=self,!self.ready else{return};self.ready=true;self.timer?.invalidate();self.timer=nil;self.web.load(URLRequest(url:URL(string:"http://127.0.0.1:18800/setup")!))}}
  }
  do{try child.run()}catch{NSAlert(error:error).runModal();exit(1)}
  web=WKWebView();web.navigationDelegate=self
  window=NSWindow(contentRect:NSRect(x:0,y:0,width:1250,height:850),styleMask:[.titled,.closable,.resizable,.miniaturizable],backing:.buffered,defer:false);window.title="User Radar";window.contentView=web;window.center();window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
  let menu=NSMenu();let root=NSMenuItem();menu.addItem(root);let sub=NSMenu();root.submenu=sub
  for (title,route) in [("接入指导 / Setup","/setup"),("邮件 / Mail","/"),("展会审核 / Exhibitors","/expansion"),("设置 / Settings","/?view=settings")]{let item=NSMenuItem(title:title,action:#selector(navigate(_:)),keyEquivalent:"");item.representedObject=route;item.target=self;sub.addItem(item)}
  sub.addItem(NSMenuItem.separator());sub.addItem(withTitle:"退出 / Quit",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q");NSApp.mainMenu=menu
  timer=Timer.scheduledTimer(withTimeInterval:0.3,repeats:true){[weak self] _ in self?.check()}
 }
 @objc func navigate(_ item:NSMenuItem){web.load(URLRequest(url:URL(string:"http://127.0.0.1:18800"+(item.representedObject as? String ?? "/"))!))}
 func check(){
  attempts+=1
  if !child.isRunning || attempts>150 {timer?.invalidate();child.terminate();if smoke{exit(1)};NSAlert(error:NSError(domain:"User Radar",code:1,userInfo:[NSLocalizedDescriptionKey:"Local service could not start. Check the application logs."])).runModal();NSApp.terminate(nil);return}

 }
 func webView(_ view:WKWebView,didFinish navigation:WKNavigation!){
  if smoke {view.evaluateJavaScript("document.querySelector('h1')?.textContent"){[weak self] value,error in self?.child.terminate();self?.child.waitUntilExit();exit(error==nil && (value as? String)=="首次接入指导" ? 0:1)}}
 }
 func webView(_ view:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void){
  guard let url=action.request.url else{decisionHandler(.cancel);return}
  if url.host=="127.0.0.1"{decisionHandler(.allow);return}
  if ["http","https","mailto"].contains(url.scheme ?? ""){NSWorkspace.shared.open(url)};decisionHandler(.cancel)
 }
 func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool {true}
 func applicationWillTerminate(_ note:Notification){timer?.invalidate();if child?.isRunning==true{child.terminate();child.waitUntilExit()}}
}
let app=NSApplication.shared;let delegate=Shell();app.delegate=delegate;app.setActivationPolicy(.regular);app.run()
