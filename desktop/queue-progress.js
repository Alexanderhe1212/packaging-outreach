/* Presentation only: never schedules or sends mail. */
(function(root){
function progress(lead, account, now=Date.now()/1000){
 const status=lead.status, error=lead.error||'', retry=Number(lead.research_retry_at||lead.data?.research_retry_at||0);
 const result=(title,reason,next,nextAt=0)=>({title,reason,next,nextAt});
 if(['sent','replied','bounced','unsubscribed','unknown','skipped'].includes(status)){
  const labels={sent:'SMTP 已接受',replied:'已收到回复',bounced:'已退信',unsubscribed:'已退订',unknown:'发送结果待核实',skipped:'已跳过'};
  return result(labels[status],status==='sent'?'SMTP 接受不等于送达':'发送保护阻止重复联系',status==='unknown'?'人工核对发送结果':'不安排重复发送');
 }
 if(!account)return result('状态待同步','账号状态尚未读取','刷新后确认');
 if(account.paused)return result('已暂停','账号已暂停，保留当前进度','恢复后继续检查');
 if(account.worker_alive===false)return result('服务待检查','工作线程未运行','检查后台服务');
 if(status==='ready'){
  if(account.auto_send===false)return result('等待审核','自动发送已关闭','审核后发送');
  if(account.send_limit_reached)return result('等待额度重置','已达到现有发送上限','额度重置后重新检查');
  if(account.send_window_open===false)return result('等待发送时段','当前不在账号发送时段','进入发送时段后重新检查');
  const next=Number(account.next_send_at||0);
  if(next>now)return result('等待发送间隔','自动发送已开启，按现有间隔处理','最早检查',next);
  return result('排队自动发送','自动发送已开启，发送前仍会检查保护条件','等待工作线程领取');
 }
 if(status==='queued'&&retry>now)return result('等待官网复查',/429|限流/.test(error)?'官网限流，等待到期':'官网读取延后处理','最早复查',retry);
 if(status==='failed'){
  let reason='处理失败，需查看原始错误';
  if(/429|限流/i.test(error))reason='官网限流，需复核重试记录';
  else if(/403|blocked|forbidden/i.test(error))reason='官网访问受限';
  else if(/image|图片|配图/i.test(error))reason='图片检查未通过';
  else if(/email|邮箱/i.test(error))reason='公开邮箱尚未核实';
  else if(/product|产品|套装/i.test(error))reason='产品证据尚未核实';
  else if(/timeout|timed out|超时|network|ssl/i.test(error))reason='连接失败或超时';
  return result('需要复核',reason,'未安排自动重试');
 }
 const steps={queued:'排队准备',researching:'核实官网',writing:'撰写邮件',imaging:'生成并检查图片',sending:'正在提交邮件',backlog:'候选待核实'};
 return result(steps[status]||'状态待核实',status==='sending'?'请勿重复提交':'按当前流程处理','完成后更新；尚无预计时间');
}
root.QueueProgress={progress};if(typeof module!=='undefined')module.exports={progress};
})(typeof window!=='undefined'?window:globalThis);
