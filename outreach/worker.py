"""每个账号一个后台线程：收件箱检查 → 按节奏发送 → 空档里准备下一位客户。某一步失败就换下一家，不卡住。"""
import random
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import archive, config, exhibition, llm, mailer, pipeline, recommendation, store, web


def _legacy_defer_preparation(data, error, now=None):
    """Schedule bounded preparation retries without consuming an SMTP attempt."""
    now = time.time() if now is None else now
    transient = web.transient_failure(error)
    ai = isinstance(error, llm.AIError) and not error.fatal and not error.setup
    if not transient and not ai:
        return False
    deferred = isinstance(transient, web.DeferredFetch)
    rate_limited = isinstance(transient, web.urllib.error.HTTPError) and transient.code == 429
    key = 'ai_retry_count' if ai else 'research_retry_count'
    attempts = int(data.get(key, 0))
    if not deferred and attempts >= (6 if rate_limited else 3):
        data['retry_exhausted'] = True
        return False
    data[key] = attempts if deferred else attempts + 1
    delay = 5 if deferred else min(300 * 2 ** min(attempts, 7), 21600)
    until = max((vars(error if ai else transient).get('retry_at', 0) if ai or transient else 0) or 0,
                now + (web.retry_after(transient) if transient else 0))
    data['research_retry_at'] = max(float(data.get('research_retry_at') or 0), now + delay, until)
    data['retry_kind'] = 'ai' if ai else 'rate_limit' if rate_limited or deferred else 'network'
    data.pop('retry_exhausted', None)
    return True


def defer_preparation(data, error, now=None):
    from pipeline_core import features, retry_policy
    if not features.enabled('unified_retry'):
        return _legacy_defer_preparation(data,error,now)
    transient=web.transient_failure(error)
    ai=isinstance(error,llm.AIError) and not error.fatal and not error.setup
    if not transient and not ai:return False
    key='ai_retry_count' if ai else 'research_retry_count'
    try:
        result=retry_policy.decide('NETWORK' if ai else transient,data.get(key,0),now=now,
            deferred=isinstance(transient,web.DeferredFetch),
            deadline=max(float(data.get('research_retry_at') or 0),
                         float(vars(error).get('retry_at',0) or 0)))
    except Exception:
        return _legacy_defer_preparation(data,error,now)
    data.update({k:result[k] for k in ('reason_code','retry_count','next_retry_at','last_error')})
    if result['action']!='retry':
        data['retry_exhausted']=result['reason_code']=='RETRY_EXHAUSTED'
        return False
    data[key]=result['retry_count'];data['research_retry_at']=result['next_retry_at']
    data['retry_kind']='ai' if ai else 'rate_limit' if result['reason_code']=='RATE_LIMITED' or isinstance(transient,web.DeferredFetch) else 'network'
    data.pop('retry_exhausted',None)
    return True




class AccountWorker(threading.Thread):
    def __init__(self, acc_id):
        super().__init__(daemon=True, name='worker-' + acc_id)
        self.id = acc_id
        self.activity = '已暂停'
        self.error = ''
        self.fails = 0
        self.miss = 0
        self.idle = 0
        self.wake = threading.Event()
        self.stopped = False
        self.last_inbox = 0
        self.send_lock = threading.Lock()

    @property
    def activity(self):
        return self._activity

    @activity.setter
    def activity(self, value):
        if getattr(self, '_activity', None) != value:
            self.activity_since = time.time()
        self._activity = value

    # ----- state -----
    @property
    def acc(self):
        return config.account(self.id)

    @property
    def profile(self):
        return config.profile(self.acc.get('profile', 'packaging'))

    @property
    def paused(self):
        return store.get('paused_' + self.id, True)

    def set_paused(self, value):
        store.put('paused_' + self.id, bool(value))
        if not value:
            self.error, self.fails, self.miss = '', 0, 0
        self.activity = '已暂停' if value else '启动中…'
        self.wake.set()

    def sleep(self, seconds):
        self.wake.wait(seconds)
        self.wake.clear()

    # ----- main loop -----
    def run(self):
        while not self.stopped:
            try:
                if self.paused:
                    self.activity = '已暂停'
                    self.sleep(3)
                    continue
                self.idle = 0
                self.check_inbox()
                if not self.paused:
                    self.step(block=False)
                self.fails = 0
                self.sleep(self.idle) if self.idle else time.sleep(0.5)  # idle waits happen outside the turn
            except KeyError as e:
                if not any(a['id'] == self.id for a in config.load()['accounts']):
                    self.stopped = True  # account removed in settings
                else:
                    traceback.print_exc()
                    self.backoff('KeyError: %s' % e)
            except (llm.AIError, mailer.MailAuthError) as e:
                if getattr(e, 'setup', False):
                    self.error = ''
                    self.activity = '等待设置：' + str(e)
                    self.sleep(30)  # saving settings wakes the worker immediately
                elif isinstance(e, mailer.MailAuthError) or e.fatal:
                    self.error = str(e)
                    self.set_paused(True)
                    self.activity = '已自动暂停：' + str(e)
                else:
                    self.backoff(str(e))
            except Exception as e:
                traceback.print_exc()
                self.backoff('%s: %s' % (type(e).__name__, e))
            finally:
                store.set_current_lead(None)

    def backoff(self, why):
        self.fails += 1
        wait = min(15 * 2 ** min(self.fails, 5), 600)
        self.error = why[:300]
        self.activity = '出错，%d 秒后继续：%s' % (wait, why[:120])
        self.sleep(wait)

    def check_inbox(self):
        """Own mailbox only, so it runs outside the shared turn."""
        if time.time() - self.last_inbox < 60 * float(config.load().get('inbox_check_minutes', 10)):
            return
        self.last_inbox = time.time()
        self.activity = '检查收件箱（回复 / 退订 / 退信）…'
        try:
            mailer.sync_inbox(self.acc)
        except mailer.MailAuthError:
            raise
        except Exception as e:
            self.error = '收件箱检查失败：%s' % type(e).__name__
        acc = self.acc
        try:
            if archive.due(acc):
                self.activity = '存档旧邮件到本地并清理服务器邮箱…'
                archive.run(acc)
            if time.time() - (store.get('mailbox_' + self.id) or {}).get('at', 0) > 6 * 3600:
                archive.report(acc)
        except mailer.MailAuthError:
            raise
        except Exception as e:
            self.error = '邮箱存档失败：%s' % e

    def step(self, block=True):
        if self.paused:
            return
        acc = self.acc
        auto = acc.get('auto_send', True)
        wait = self.send_wait(acc)
        if wait <= 0:
            for row in store.q("SELECT id FROM leads WHERE account=? AND source='exhibition' AND status='ready' ORDER BY id", (self.id,)):
                lead = store.lead(row['id'])
                if exhibition.approved(lead):
                    return self.send(lead)
        if auto and wait <= 0:
            ready = store.next_lead(self.id, ('ready',))
            if ready:
                if ready['source'] != 'exhibition' and self.profile.get('discovery_rules') and (ready['data'].get('prospect', {}).get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+', 'A'):
                    store.update(ready['id'], status='backlog', error='当前采购项目证据待核实；保留旧草稿')
                    return
                return self.send(ready)
            due = self.followup_due(acc)
            if due:
                return self.send_followup(due)
        from pipeline_core import features
        if features.enabled('auto_followup'):
            from . import followups
            if followups.prepare(acc,self.profile):return
        buffer = max(1,min(20,int(features.option('ready_buffer_per_account',2 if auto else 5))))
        if store.count(self.id, 'ready') < buffer or store.next_lead(self.id, ('queued',)):
            return self.prepare_one()
        if not auto:
            self.activity = '已备好 %d 封，等你在列表里审核发送' % store.count(self.id, 'ready')
        elif self.limit_reached(acc):
            self.activity = '今日已达发送上限，明天自动继续'
        elif not self.in_hours(acc):
            self.activity = '不在发送时段（北京时间 %s 点），已备好 %d 封' % ('–'.join(map(str, acc['send_hours_beijing'])), store.count(self.id, 'ready'))
        else:
            self.activity = '下一封 %d 分 %02d 秒后发送' % (wait // 60, wait % 60)
        if block:
            self.sleep(min(max(wait, 5), 30))
        else:
            self.idle = min(max(wait, 5), 30)

    def limit_reached(self, acc):
        """Per-account cap (0 / empty = unlimited) and an optional cap for all accounts together."""
        mine = int(acc.get('daily_limit') or 0)
        if mine and store.sent_today(self.id) >= mine:
            return True
        total = int(config.load().get('daily_limit_total') or 0)
        if total and sum(store.sent_today(a['id']) for a in config.load()['accounts']) >= total:
            return True
        return False

    def in_hours(self, acc):
        hours = acc.get('send_hours_beijing')
        if not hours:
            return True
        h, (start, end) = datetime.now(store.BJ).hour, hours
        return start <= h < end if start < end else (h >= start or h < end)

    def send_wait(self, acc):
        if self.limit_reached(acc) or not self.in_hours(acc):
            return 600
        return max(0, int(store.get('next_send_' + self.id, 0) - time.time()))

    # ----- prepare one customer end-to-end -----
    def prepare_one(self):
        shared_wait = web.FETCH_GUARD.wait_seconds()
        if shared_wait:
            self.activity = '跨域突发保护：%d 秒后继续准备（最长 30 秒）' % shared_wait
            self.idle = min(shared_wait, 30)
            return
        acc, prof = self.acc, self.profile
        lead = store.next_lead(self.id, ('queued',))
        if lead is None:
            from .radar import queue_second_contact
            lead=queue_second_contact(self.id)
        radar_source=store.get('radar_source',{})
        if lead is None and radar_source.get('enabled') and self.id in (radar_source.get('accounts') or [radar_source.get('account')]):
            from . import radar
            self.activity='从用户雷达领取下一家客户…'
            try:
                lead=radar.pull_one(self.id)
            except Exception:
                self.activity='用户雷达暂时不可用，等待连接恢复'
                self.idle=30
                return
            if lead is None:
                self.activity='等待用户雷达保存新的客户'
                self.idle=30
                return
        if lead is None:
            recycled=store.queue_recontact(self.id)
            lead=store.lead(recycled) if recycled else None
        if lead is None:
            cand = store.claim_candidate(self.id)
            if cand is None:
                self.activity = '寻找一批新客户…'
                added = pipeline.discover(acc, prof)
                if not added:
                    self.miss += 1
                    report = store.get('discovery_last_' + self.id, {})
                    self.activity = ('本轮搜索未找到候选客户，正在更换方向' if not report.get('raw_count')
                                     else '本轮候选未通过采购证据或联系条件检查，正在继续寻找')
                    self.idle = max(600, min(300 * self.miss, 1800)) if prof.get('discovery_rules') else min(10 * self.miss, 120)  # wait outside the turn
                else:
                    self.miss = 0
                return
            self.activity = '读取官网：' + cand['domain']
            try:
                try:
                    detail=__import__('json').loads(cand.get('note') or '{}')
                except (ValueError,TypeError):
                    detail={}
                if prof.get('discovery_rules') and detail.get('opportunity_tier') not in ('A+','A'):
                    store.mark_candidate(cand['domain'], 'backlog', '新策略：需求证据待核实，不进入写信队列')
                    return
                target=detail.get('product_url') or cand['domain']
                if web.root_domain(web.host(target))!=web.root_domain(cand['domain']):
                    raise web.CrawlError('候选商品来源跨品牌')
                prospect, photo = pipeline.research(acc, target)
            except (web.CrawlError, web.DeferredFetch, web.urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if web.transient_failure(e):
                    store.defer_candidate(cand['domain'], e)
                else:
                    store.mark_candidate(cand['domain'], 'skipped', str(e))
                self.error = ''
                self.activity = '跳过 %s（%s）' % (cand['domain'], e)
                return
            except llm.AIError:
                store.mark_candidate(cand['domain'], 'new', '模型暂不可用，等待恢复')
                raise
            except Exception as e:
                store.mark_candidate(cand['domain'], 'skipped', '研究异常：%s' % type(e).__name__)
                self.error = ''
                self.activity = '跳过 %s（研究异常：%s）' % (cand['domain'], type(e).__name__)
                return
            store.mark_candidate(cand['domain'], 'used')
            prospect['focus'] = detail.get('match_reason') or detail.get('note') or cand.get('note','')
            prospect['discovery_evidence'] = detail
            prospect['purchase_signal'] = 'confirmed_procurement' if detail.get('opportunity_tier') in ('A+','A') else 'fit_inference'
            lid = store.claim_prospect(self.id, prospect)
            if not lid:
                self.activity = '跳过重复或已抑制客户：' + prospect['domain']
                return
            if self.paused:
                store.update(lid, status='queued')
                return
            return self.process(store.lead(lid), photo)
        return self.process(lead, None)

    def process(self, lead, photo):
        acc, prof, lid, d = self.acc, dict(self.profile, image_optional=False), lead['id'], lead['data']
        if (not d.get('prospect') and int(d.get('research_retry_count',0)) >= 6
                and ('429' in lead.get('error','') or d.get('retry_kind')=='rate_limit')):
            d['retry_exhausted'] = True
            store.update(lid,status='failed',data=d,error='自动补查已达上限，待复核来源：'+lead.get('error','限流'))
            return
        store.set_current_lead(lid)
        try:
            manual = d.get('manual', {})
            cached = d.get('prospect') or {}
            target = manual.get('url', '')
            selected_path = web.urlsplit(target if '//' in target else '//' + target).path.strip('/')
            # Old text fallbacks lost the selected page; refresh once before using their draft.
            refresh_context = bool(cached and prof.get('inquiry_first') and not prof.get('require_abc')
                                   and selected_path and not cached.get('site_description_source')
                                   and not cached.get('product_url') and not cached.get('introduction_only'))
            if not cached or refresh_context:
                self.activity = '读取手动添加的客户：' + manual.get('url', '')
                store.update(lid, status='researching', error='')
                contact = dict(manual.get('radar') or {})
                if manual.get('email_recheck'):contact['recheck_email']=True
                introduction = prof.get('inquiry_first') and not prof.get('require_abc') and contact and (contact.get('batch_id')=='us-exhibitions-2022-2026' or manual.get('introduction_mode'))
                if introduction:
                    d['prospect'], photo = recommendation.research(acc, contact)
                else:
                    try:
                        d['prospect'], photo = pipeline.research(acc, manual.get('url', ''), manual.get('email', ''), manual=True, email_sources=contact.get('sources', []))
                    except web.CrawlError as error:
                        if contact and prof.get('inquiry_first') and not prof.get('require_abc') and str(error)=='官网业务未能核实包装匹配度':
                            d['prospect'], photo = recommendation.research(acc, contact)
                        else:raise
                if refresh_context:
                    d.pop('plan', None)
                p = d['prospect']
                if not store.claim_prospect(self.id,p,lid=lid):
                    store.update(lid,status='skipped',error='重复或已抑制客户')
                    return
                store.update(lid, company=p['company'], domain=p['domain'], email=p['email'], data=d)
            p = d['prospect']
            from .prospect_filter import prospect_reason
            reason = prospect_reason(p)
            if reason:raise web.IneligibleProspect(reason)
            contact = (d.get('manual') or {}).get('radar') or {}
            if contact.get('company'):
                p['recipient_company'] = contact['company']
            # Carry original quotations even when the parser selected a heading,
            # or a recheck changed the address. The writer resolves the exact email.
            fields = contact.get('evidence_by_field') or {}
            p['contact_identity_evidence'] = fields.get('identity', []) + fields.get('email', [])
            if prof.get('require_abc') and not p.get('concept_ready'):
                self.activity = '重新核实官网邮箱与真实产品：' + lead['company']
                p, photo = pipeline.research(acc, p.get('website') or lead['domain'], p.get('email',''), manual=True)
                d['prospect'] = p
                d.pop('plan', None)
                d.pop('image_prompt', None)
                store.update(lid, data=d, image='')
            if d.get('revalidate_opportunity') and prof.get('discovery_rules'):
                from .opportunity import verify
                evidence=p.get('discovery_evidence') or {}
                verify(evidence)
                p['discovery_evidence']=evidence
                d['revalidate_opportunity']=False
                store.update(lid,data=d)
            if prof.get('discovery_rules') and (p.get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+','A'):
                store.update(lid, status='backlog', error='当前项目采购证据待核实；保留后备')
                return
            name = p.get('customer_brand') or p['company']
            if photo is None and p.get('product_asset'):
                try:
                    from pipeline_core.evidence import read_asset
                    photo=read_asset(p['product_asset'])
                except Exception:pass
            if photo is None and p.get('product_image_url') and prof.get('image',{}).get('enabled',True):
                photo, _ = web.product_image(p['product_image_url'])
            if self.paused:
                store.update(lid,status='queued',data=d)
                return
            needs_image = prof.get('image', {}).get('enabled', True) and (not prof.get('hybrid_concepts') or p.get('concept_ready',False))
            if needs_image and prof.get('hybrid_concepts') and not photo:
                if not prof.get('image_optional'):
                    raise web.CrawlError('无法读取真实产品参考图，暂不生成或发送效果图邮件')
                p['concept_ready'] = False
                needs_image = False
                d.pop('plan', None)
            if not d.get('plan'):
                self.activity = '写个性化邮件 + 设计方案：' + name
                store.update(lid, status='writing', error='')
                try:
                    d['plan'] = pipeline.write(acc, prof, p, photo)
                except (ValueError, llm.AIError):
                    if not prof.get('image_optional') or not p.get('concept_ready'):
                        raise
                    p['concept_ready'] = False
                    needs_image = False
                    d['plan'] = pipeline.write(acc, prof, p, None)
                store.update(lid, data=d, subject=d['plan']['subject'], body=d['plan']['body'])
            if self.paused:
                store.update(lid,status='queued',data=d)
                return
            if needs_image and not (lead.get('image') and d.get('image_prompt')):
                self.activity = '生成包装效果图：' + name
                store.update(lid, status='imaging')
                try:
                    pic, prompt = pipeline.make_image(acc, prof, p, d['plan'], photo)
                    path = config.data_dir() / 'accounts' / self.id / 'images' / ('%d.jpg' % lid)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(pic)
                    d['image_prompt'], d['had_reference'] = prompt, photo is not None
                    store.update(lid, image=str(path))
                except (ValueError, llm.AIError, OSError) as exc:
                    if not prof.get('image_optional'):
                        raise
                    from . import problems
                    problems.add({'title':'Concept image needs review — lead #'+str(lid), 'detail':str(exc)[:500]+'; image omitted and email rewritten without attachment claims.'})
                    d['image_skipped_reason'] = str(exc)[:200]
                    p['concept_ready'] = False
                    d.pop('image_prompt', None)
                    self.activity = '图片暂不可用，改写为纯文字开发邮件'
                    d['plan'] = pipeline.write(acc, prof, p, None)
                    store.update(lid, image='', subject=d['plan']['subject'], body=d['plan']['body'])
            store.update(lid, status='ready', data=d, error='')
            self.error = ''
            self.activity = '已准备好：' + name
        except web.IneligibleProspect as e:
            d['screening'] = {'eligible':False, 'reason':str(e), 'checked_at':time.time()}
            store.update(lid,status='skipped',error=str(e),data=d)
            self.activity = '已筛除不匹配客户，继续下一家'
        except llm.AIError as e:
            if defer_preparation(d, e):
                store.update(lid, status='queued', error='AI 暂时不可用，已安排重试：'+str(e)[:220], data=d)
                self.activity = 'AI 任务稍后重试；继续下一家'
                return
            store.update(lid, status='queued' if e.fatal else 'failed', error=str(e)[:300], data=d)
            raise
        except (ValueError, web.CrawlError, web.DeferredFetch, web.urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if defer_preparation(d, e):
                store.update(lid, status='queued', error='官网暂时不可用，延迟复核：' + str(e)[:220], data=d)
                self.activity = '官网限流，稍后复核；继续下一家'
            else:
                prefix = '自动补查已达上限，待复核来源：' if d.get('retry_exhausted') else ''
                store.update(lid, status='failed', error=prefix+str(e)[:250], data=d)
                self.activity = '跳过：%s' % e
        except Exception as e:
            store.update(lid, status='failed', error='%s: %s' % (type(e).__name__, str(e)[:250]), data=d)
            raise

    # ----- send -----
    def send(self, lead, manual=False, origin=None, followup=False, dry_run=False):
        # Account-local lock; another account can still search, generate or send.
        if not self.send_lock.acquire(blocking=False):
            store.audit('send_denied',self.id,lead['id'],origin,'sending')
            return 'sending'
        token=None
        try:
            lead=store.lead(lead['id']);acc=self.acc
            if not lead or lead['account']!=self.id:
                return 'account_mismatch'
            if lead['source'] == 'exhibition' and not exhibition.approved(lead):
                return 'exhibition_review_required'
            if lead['source'] != 'exhibition' and self.profile.get('discovery_rules') and (lead['data'].get('prospect',{}).get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+','A'):
                store.audit('send_denied',self.id,lead['id'],origin,'procurement_evidence_required')
                return 'procurement_evidence_required'
            from .prospect_filter import prospect_reason
            reason = prospect_reason(lead['data'].get('prospect') or {})
            if reason:
                if lead['status'] == 'ready' and not lead.get('sent_at') and not lead.get('message_id'):
                    store.update(lead['id'],status='skipped',error=reason)
                store.audit('send_denied',self.id,lead['id'],origin,'non_target_business')
                return 'non_target_business'
            img=Path(lead['image']).read_bytes() if lead.get('image') and Path(lead['image']).exists() else None
            if self.profile.get('require_abc'):
                p = lead['data'].get('prospect', {})
                plan = lead['data'].get('plan', {})
                if not (p.get('email_verified') and p.get('product_name') and p.get('product_url') and p.get('concept_ready') and img and all(plan.get(k) for k in ('a','b','c'))):
                    store.update(lead['id'], status='failed', error='缺少官网邮箱、真实产品或完整 ABC 效果图，未发送')
                    return 'concept_requirements_missing'

            if lead['data'].get('prospect',{}).get('concept_ready') and lead['data'].get('plan',{}).get('c') and not img:
                store.audit('send_denied',self.id,lead['id'],origin,'concept_image_missing')
                return 'concept_image_missing'
            p = lead['data'].get('prospect', {})
            if not followup and p.get('recipient_identity_confirmed'):
                expected_greeting = 'Hi ' + pipeline.recipient_label(p) + ','
                if not str(lead.get('body') or '').lstrip().startswith(expected_greeting):
                    if lead['status'] == 'ready' and not lead.get('sent_at') and not lead.get('message_id'):
                        store.update(lead['id'], status='failed', error='已核实本人姓名但邮件称呼不一致，未发送；需重新生成')
                    store.audit('send_denied', self.id, lead['id'], origin, 'recipient_greeting_mismatch')
                    return 'recipient_greeting_mismatch'
            if not img:
                store.audit('send_denied',self.id,lead['id'],origin,'concept_image_missing')
                return 'concept_image_missing'
            msg=mailer.build_followup(acc,lead,self.profile) if followup else mailer.build(acc,lead,img)
            origin=origin or {'source':'manual_internal' if manual else ('followup' if followup else 'scheduler')}
            if dry_run:
                reason=store._conflict(store.db(),lead)
                result=reason or 'dry_run_ready'
                store.event(lead['id'],'send_check',result,result.upper(),self.id)
                return result
            from .send_guard import check
            guard_reason=check(acc,lead)
            if guard_reason:return guard_reason
            token,reason=store.reserve_send(lead['id'],acc,str(msg['Message-ID']),origin,followup,expected=lead)
            if not token:
                return reason
            self.activity='发送给 %s <%s>'%(lead['company'],lead['email'])
            try:
                result,note=mailer.send(acc,msg,before_data=lambda:store.transport_allowed(token))
            except mailer.MailAuthError:
                store.finish_send(token,'auth_error','邮箱认证失败；保持原账号，需检查配置',time.time()+120)
                self.set_paused(True)
                raise
            except Exception as e:
                # A custom transport or unexpected exception may have passed DATA.
                result,note='unknown','传输异常，需核实状态：'+type(e).__name__
            now=time.time();lo,hi=acc.get('send_interval_minutes',[4,9])
            next_at=now+random.uniform(float(lo),float(hi))*60
            from pipeline_core import features
            if features.enabled('send_guard'):next_at=max(next_at,now+random.uniform(90,300))
            store.finish_send(token,result,note,next_at)
            if result in ('sent','unknown'):
                try:
                    mailer.save_eml(str(lead['id'])+('-followup' if followup else ''),msg,self.id,lead,img)
                except Exception as e:
                    store.audit('archive_failed',self.id,lead['id'],origin,type(e).__name__)
                    self.error='发送结果已保存；本地邮件存档失败：'+type(e).__name__
            return result
        finally:
            self.send_lock.release()

    def schedule_next(self, acc, now):
        lo, hi = acc.get('send_interval_minutes', [4, 9])
        store.put('next_send_' + self.id, now + random.uniform(float(lo), float(hi)) * 60)

    # ----- optional single follow-up, same thread, no AI tokens -----
    def followup_due(self, acc):
        from pipeline_core import features
        if features.enabled('auto_followup'):
            from .followups import candidate
            lead=candidate(self.id)
            return lead if lead and (lead['data'].get('followup_ready') or {}).get('index')==lead['followups']+1 else None
        fu = self.profile.get('followup', {})
        enabled = acc.get('followup_enabled', fu.get('enabled', False))
        if not enabled:
            return None
        days = max(7, float(acc.get('followup_days', fu.get('days', 5))))
        r = store.q("SELECT id FROM leads WHERE account=? AND status='sent' AND followups=0 AND reply_at IS NULL "
                    "AND message_id!='' AND sent_at<? ORDER BY sent_at LIMIT 1", (self.id, time.time() - days * 86400), one=True)
        return store.lead(r['id']) if r else None

    def send_followup(self, lead):
        return self.send(lead,followup=True,origin={'source':'followup'})
