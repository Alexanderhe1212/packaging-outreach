"""Reviewed packaging-distributor collaboration; transport guards stay in Worker."""
import hashlib,json,re,time
from . import web,store,config,pipeline

def digest(lead):
    return hashlib.sha256(json.dumps([lead.get(k,"") for k in ("id","account","domain","email","subject","body")],ensure_ascii=False).encode()).hexdigest()

def eligible(lead):
    p=lead.get("data",{}).get("distributor_review",{})
    return (p.get("kind")=="packaging_distributor" and p.get("digest")==digest(lead)
            and p.get("public_email_verified") is True and p.get("approved") is True
            and all(p.get(k) for k in ("product_quote","source_url","exhibitor_url","exhibitor_quote"))
            and 0<=time.time()-p.get("checked_at",0)<7*86400)

def excerpt(url,quote,official_domain=None):
    if not isinstance(quote,str) or not 20<=len(quote)<=1800:raise ValueError("官网原文证据长度无效")
    raw,final=web.page(url)
    if official_domain and web.root_domain(web.host(final))!=official_domain:raise ValueError("证据跳转至其他公司")
    compact=lambda s:re.sub(r"\s+"," ",s).strip().casefold()
    if compact(quote) not in compact(web.strip_tags(raw)):raise ValueError("官网原文未核实")
    return final

def prepare(data):
    lead=store.lead(int(data["id"]))
    if not lead or lead["status"] not in ("failed","radar_review","ready"):raise ValueError("只能审核未发送的静止记录")
    if lead.get("sent_at") or lead.get("message_id") or lead.get("reply_at"):raise ValueError("已有联系记录，不可重新准备")
    acc=config.account(lead["account"])
    if acc.get("text_only") is not True:raise ValueError("经销商合作入口当前仅支持已启用的纯文字模式")
    dom=web.root_domain(web.host(data["website"]))
    if dom!=web.root_domain(lead["domain"]) or data["email"].lower()!=lead["email"].lower():raise ValueError("客户归属或邮箱不一致")
    if web.root_domain(web.host(data["contact_url"]))!=dom or web.root_domain(web.host(data["product_url"]))!=dom:raise ValueError("需要同公司官网证据")
    email_source=web.verify_email(data["email"],data["contact_url"],data["website"],data["company"])
    excerpt(data["product_url"],data["product_quote"],dom)
    excerpt(data["exhibitor_url"],data["exhibitor_quote"])
    if data.get("review_approved") is not True:raise ValueError("尚未审核")
    subject=data["subject"].strip();body=data["body"].strip()
    if not body.startswith("Hi "+data["company"]+" team,") or len(body)<120 or not subject:raise ValueError("称呼或正文不完整")
    if data["product_reference"].casefold() not in body.casefold():raise ValueError("必须写明已核实包装业务")
    if not data["product_reference"].strip() or data["product_reference"].casefold() not in data["product_quote"].casefold():raise ValueError("包装业务引用与证据不一致")
    with store._lock:
        current=store.lead(lead["id"])
        if current["status"]!=lead["status"] or current.get("message_id") or current.get("sent_at"):raise ValueError("记录已变化，请重新审核")
        prospect=dict(company=data["company"],domain=lead["domain"],website=data["website"],email=lead["email"],email_verified=True,email_source=email_source,recipient_company=data["company"])
        if not store.claim_prospect(lead["account"],prospect,lid=lead["id"]):raise ValueError("客户已抑制或重复，未交接")
        body=pipeline.clean_body(body,acc);ready=dict(current,subject=subject,body=body)
        d=current["data"];d["prospect"]=prospect;d["plan"]={"subject":subject,"body":body}
        d["distributor_review"]=dict(kind="packaging_distributor",digest=digest(ready),public_email_verified=True,approved=True,product_quote=data["product_quote"],source_url=data["product_url"],exhibitor_url=data["exhibitor_url"],exhibitor_quote=data["exhibitor_quote"],checked_at=time.time())
        store.update(lead["id"],company=data["company"],status="ready",error="",subject=subject,body=body,data=d)
        store.audit("distributor_reviewed",lead["account"],lead["id"],data.get("_origin"),"approved")
    return {"id":lead["id"],"status":"ready"}
