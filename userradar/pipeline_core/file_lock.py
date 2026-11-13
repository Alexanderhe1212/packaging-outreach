"""Conservative cross-platform advisory file locks (shared requests are exclusive on Windows)."""
import sys,time
LOCK_EX=2
LOCK_SH=1
LOCK_NB=4
LOCK_UN=8

def flock(file,operation):
    if sys.platform!='win32':
        import fcntl
        return fcntl.flock(file,operation)
    import msvcrt,os
    fd=file if isinstance(file,int) else file.fileno()
    os.lseek(fd,0,os.SEEK_SET)
    if operation & LOCK_UN:
        return msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
    if os.fstat(fd).st_size==0:
        os.write(fd,b'\0');os.lseek(fd,0,os.SEEK_SET)
    while True:
        try:return msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        except OSError:
            if operation & LOCK_NB:raise
            time.sleep(.05)
