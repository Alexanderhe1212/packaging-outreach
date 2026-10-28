"""Descriptive evidence dimensions, never an authorization to send."""
def describe(lead):
 d=lead.get('data') or {};p=d.get('prospect') or {};c=(d.get('manual') or {}).get('radar') or {}
 def field(status,reason):return {'status':status,'reason_code':reason}
 fit=field('failed','PERMANENT_EXCLUDE') if d.get('screening',{}).get('eligible') is False else field('passed','PRODUCT_VERIFIED') if p.get('product_name') and p.get('product_url') else field('pending_review','FIT_UNCONFIRMED')
 identity=field('none','IDENTITY_UNCONFIRMED')
 if c.get('contact_kind')=='company_public':identity=field('generic_company','PUBLIC_COMPANY_CHANNEL')
 elif p.get('recipient_identity_confirmed'):
  buyer=c.get('procurement_authority_confirmed') is True
  identity=field('named_buyer' if buyer else 'named_other','BUYER_VERIFIED' if buyer else 'PERSON_VERIFIED_ROLE_UNCONFIRMED')
 elif lead.get('email'):identity=field('generic_company','PERSON_NOT_VERIFIED')
 email=field('public_verified','PUBLIC_SOURCE_VERIFIED') if p.get('email_verified') else field('indirect_unverified','PUBLIC_SOURCE_REQUIRED')
 if lead.get('status')=='bounced':email=field('bounced','BOUNCED')
 elif not lead.get('email'):email=field('invalid','NO_EMAIL')
 reason='PREPARATION_INCOMPLETE'
 if lead.get('status') in ('sent','replied','unsubscribed','bounced','unknown','sending'):reason=lead['status'].upper()
 elif lead.get('status')=='ready':reason='FINAL_SEND_GATES_REQUIRED'
 # Eligible here means ready for final checks, not permission to bypass them.
 send=field('eligible' if lead.get('status')=='ready' and fit['status']=='passed' and email['status']=='public_verified' and lead.get('image') else 'blocked',reason)
 return dict(fit_status=fit,contact_identity=identity,email_evidence=email,send_eligibility=send)
