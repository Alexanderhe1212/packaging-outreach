"""Private content-addressed PNGs; only a selected job hydrates image bytes."""
import base64,hashlib,os,re,tempfile
from pathlib import Path

IMAGE_KEYS={'concept_png','png_base64'}

def pack(root,value):
    if isinstance(value,list):return [pack(root,v) for v in value]
    if not isinstance(value,dict):return value
    result={}
    for key,item in value.items():
        if key not in IMAGE_KEYS or not isinstance(item,str):
            result[key]=pack(root,item);continue
        raw=base64.b64decode(item,validate=True)
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw)>12*1024*1024:raise ValueError('Invalid or oversized PNG')
        digest=hashlib.sha256(raw).hexdigest();directory=Path(root)/'image-assets';directory.mkdir(exist_ok=True)
        path=directory/(digest+'.png')
        if path.exists():
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Image asset changed')
        else:
            fd,temp=tempfile.mkstemp(prefix='.image-',dir=directory)
            try:
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                os.replace(temp,path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
        result[key]={'$image_blob':digest,'bytes':len(raw)}
    return result

def hydrate(root,value):
    if isinstance(value,list):return [hydrate(root,v) for v in value]
    if not isinstance(value,dict):return value
    if '$image_blob' in value:
        digest=value['$image_blob']
        if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Invalid image reference')
        path=Path(root)/'image-assets'/(digest+'.png')
        if path.is_symlink():raise ValueError('Image symlinks are not permitted')
        raw=path.read_bytes()
        if len(raw)!=value.get('bytes') or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Image asset changed')
        return base64.b64encode(raw).decode()
    return {k:hydrate(root,v) for k,v in value.items()}
