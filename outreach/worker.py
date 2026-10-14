"""每个账号一个后台线程：收件箱检查 → 按节奏发送 → 空档里准备下一位客户。某一步失败就换下一家，不卡住。"""
import random
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import archive, config, llm, mailer, pipeline, store, web




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
        if auto and wait <= 0:
            ready = store.next_lead(self.id, ('ready',))
            if ready:
                return self.send(ready)
            due = self.followup_due(acc)
            if due:
                return self.send_followup(due)
        buffer = 2 if auto else 5
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
        acc, prof = self.acc, self.profile
        lead = store.next_lead(self.id, ('queued',))
        if lead is None:
            cand = store.claim_candidate(self.id)
            if cand is None:
                self.activity = '寻找一批新客户…'
                added = pipeline.discover(acc, prof)
                if not added:
                    self.miss += 1
                    self.activity = '这一批都是重复或无效客户，换个方向再找'
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
            except web.CrawlError as e:
                store.mark_candidate(cand['domain'], 'skipped', str(e))
                self.error = ''
                self.activity = '跳过 %s（%s）' % (cand['domain'], e)
                return
            except Exception:
                store.mark_candidate(cand['domain'], 'new', '研究中断，待下轮核实')
                raise
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
        acc, prof, lid, d = self.acc, self.profile, lead['id'], lead['data']
        store.set_current_lead(lid)
        try:
            if not d.get('prospect'):
                manual = d.get('manual', {})
                self.activity = '读取手动添加的客户：' + manual.get('url', '')
                store.update(lid, status='researching', error='')
                d['prospect'], photo = pipeline.research(acc, manual.get('url', ''), manual.get('email', ''), manual=True)
                p = d['prospect']
                if not store.claim_prospect(self.id,p,lid=lid):
                    store.update(lid,status='skipped',error='重复或已抑制客户')
                    return
                store.update(lid, company=p['company'], domain=p['domain'], email=p['email'], data=d)
            p = d['prospect']
            if prof.get('discovery_rules') and (p.get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+','A'):
                store.update(lid, status='backlog', error='当前项目采购证据待核实；保留后备')
                return
            name = p.get('customer_brand') or p['company']
            if photo is None and p.get('product_image_url'):
                photo, _ = web.product_image(p['product_image_url'])
            if self.paused:
                store.update(lid,status='queued',data=d)
                return
            if not d.get('plan'):
                self.activity = '写个性化邮件 + 设计 A/B：' + name
                store.update(lid, status='writing', error='')
                d['plan'] = pipeline.write(acc, prof, p, photo)
                store.update(lid, data=d, subject=d['plan']['subject'], body=d['plan']['body'])
            if self.paused:
                store.update(lid,status='queued',data=d)
                return
            if prof.get('image', {}).get('enabled', True) and not (lead.get('image') and d.get('image_prompt')):
                self.activity = '生成 A/B 效果图：' + name
                store.update(lid, status='imaging')
                pic, prompt = pipeline.make_image(acc, prof, p, d['plan'], photo)
                path = config.data_dir() / 'accounts' / self.id / 'images' / ('%d.jpg' % lid)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(pic)
                d['image_prompt'], d['had_reference'] = prompt, photo is not None
                store.update(lid, image=str(path))
            store.update(lid, status='ready', data=d, error='')
            self.error = ''
            self.activity = '已准备好：' + name
        except llm.AIError as e:
            store.update(lid, status='queued' if e.fatal else 'failed', error=str(e)[:300], data=d)
            raise
        except (ValueError, web.CrawlError) as e:
            store.update(lid, status='failed', error=str(e)[:300], data=d)
            self.activity = '跳过：%s' % e

    # ----- send -----
    def send(self, lead, manual=False, origin=None, followup=False):
        # Account-local lock; another account can still search, generate or send.
        if not self.send_lock.acquire(blocking=False):
            store.audit('send_denied',self.id,lead['id'],origin,'sending')
            return 'sending'
        token=None
        try:
            lead=store.lead(lead['id']);acc=self.acc
            if not lead or lead['account']!=self.id:
                return 'account_mismatch'
            if self.profile.get('discovery_rules') and (lead['data'].get('prospect',{}).get('discovery_evidence') or {}).get('opportunity_tier') not in ('A+','A'):
                store.audit('send_denied',self.id,lead['id'],origin,'procurement_evidence_required')
                return 'procurement_evidence_required'
            img=Path(lead['image']).read_bytes() if lead.get('image') and Path(lead['image']).exists() else None
            msg=mailer.build_followup(acc,lead,self.profile) if followup else mailer.build(acc,lead,img)
            origin=origin or {'source':'manual_internal' if manual else ('followup' if followup else 'scheduler')}
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
        fu = self.profile.get('followup', {})
        enabled = acc.get('followup_enabled', fu.get('enabled', False))
        if not enabled:
            return None
        days = float(acc.get('followup_days', fu.get('days', 5)))
        r = store.q("SELECT id FROM leads WHERE account=? AND status='sent' AND followups=0 AND reply_at IS NULL "
                    "AND message_id!='' AND sent_at<? ORDER BY sent_at LIMIT 1", (self.id, time.time() - days * 86400), one=True)
        return store.lead(r['id']) if r else None

    def send_followup(self, lead):
        return self.send(lead,followup=True,origin={'source':'followup'})
