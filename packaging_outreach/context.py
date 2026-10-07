"""Small model hints; the caller retains the complete local exclusion sets."""
import json

def hints(values,seed,max_items=160,max_chars=3500):
    values=sorted(set(values));result=[];used=0
    if not values:return result
    offset=(seed*37)%len(values)
    for index in range(len(values)):
        value=values[(offset+index)%len(values)];size=len(json.dumps(value))+2
        if used+size>max_chars:continue
        result.append(value);used+=size
        if len(result)>=max_items:break
    return result
