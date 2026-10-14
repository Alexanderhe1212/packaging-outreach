#!/usr/bin/env python3
"""Build a native macOS applet; never launches Terminal or changes account state."""
import argparse
import json
import plistlib
import shlex
import subprocess
import tempfile
from pathlib import Path


def build(destination, python, root, logdir):
    destination, root, logdir = map(lambda p: Path(p).resolve(), (destination, root, logdir))
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite existing launcher: {destination}')
    # AppleScript runs only shell commands, not application automation / System Events.
    command = ('mkdir -p ' + shlex.quote(str(logdir)) + '; '
               + '/usr/bin/nohup ' + shlex.quote(str(python)) + ' '
               + shlex.quote(str(root / 'app.py')) + ' open >> '
               + shlex.quote(str(logdir / 'launcher.log')) + ' 2>&1 < /dev/null &')
    source = 'on run\n  do shell script ' + json.dumps(command) + '\nend run\n'
    with tempfile.TemporaryDirectory() as temp:
        script = Path(temp) / 'launcher.applescript'
        script.write_text(source)
        subprocess.run(['/usr/bin/osacompile', '-o', str(destination), str(script)], check=True)
    plist_path = destination / 'Contents/Info.plist'
    with plist_path.open('rb') as f:
        metadata = plistlib.load(f)
    metadata.update(CFBundleIdentifier='com.outreachpilot.desktop', CFBundleName='Outsearch Pilot',
                    CFBundleDisplayName='Outsearch Pilot', CFBundleShortVersionString='1.3.1', LSUIElement=True)
    with plist_path.open('wb') as f:
        plistlib.dump(metadata, f)
    # Re-seal our own newly generated local bundle after metadata changes.
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(destination)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', str(destination)], check=True)
    # No quarantine changes, login items or background permissions.
    return destination


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('destination'); p.add_argument('--python', required=True)
    p.add_argument('--root', required=True); p.add_argument('--logdir', required=True)
    a = p.parse_args()
    print(build(a.destination, a.python, a.root, a.logdir))
