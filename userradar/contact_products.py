"""Product responsibilities quoted from an already attributed contact block."""
import copy,re
LABEL=re.compile(r'^(?:product responsibilities|products? handled|responsible for|负责产品|产品分工|负责品类)\s*[:：]\s*(.{2,180})$',re.I)
TITLE=re.compile(r'^(?:sales|product|category) manager\s*[-–—:]\s*(.{2,100})$',re.I)
def annotate_people(people):
 result=copy.deepcopy(people)
 for p in result:
  observations=[];quote=p.get('evidence','');source=p.get('source','')
  # Never borrow a company-wide product list or infer ownership from an email.
  if source and p.get('name') and p.get('email') and p['name'].casefold() in quote.casefold() and p['email'].casefold() in quote.casefold() and len(quote)<=1400:
   for line in quote.splitlines():
    line=line.strip();match=LABEL.fullmatch(line) or TITLE.fullmatch(line)
    if match and '@' not in match[1]:
     value={'text':match[1].strip(),'source':source,'quote':line}
     if value not in observations:observations.append(value)
  p['product_responsibilities']=observations
 return result
