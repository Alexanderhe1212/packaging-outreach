"""Provision this Mac's extension without exposing its pairing credential."""
import base64
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent

def prepare():
    manifest=ROOT/'chrome-extension/manifest.json'
    data=json.loads(manifest.read_text())
    if not data.get('key'):
        private=subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048'],capture_output=True,check=True).stdout
        public=subprocess.run(['openssl','pkey','-pubout','-outform','DER'],input=private,capture_output=True,check=True).stdout
        data['key']=base64.b64encode(public).decode()
        manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    from extension_api import get_configuration
    configuration=get_configuration()
    file=ROOT/'chrome-extension/config.js'
    fd=os.open(str(file),os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:out.write('globalThis.USER_RADAR_CONFIG = '+json.dumps(configuration)+';\n')
    file.chmod(0o600)
    return ROOT/'chrome-extension'

if __name__=='__main__':
    folder=prepare()
    from desktop_launcher import ensure_server
    ensure_server()
    subprocess.run(['/usr/bin/open',str(folder)],check=True)
    subprocess.run(['/usr/bin/open','-a','Google Chrome','chrome://extensions/'],check=True)
    print('Chrome 扩展页已打开。开启开发者模式，点击加载已解压的扩展程序，选择已打开的插件文件夹。')
