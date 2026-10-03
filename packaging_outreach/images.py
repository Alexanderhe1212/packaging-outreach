"""Bounded PNG validation; visual/engineering approval remains separate."""
import struct,zlib

def validate_png(raw):
    if len(raw)>8*1024*1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Valid PNG required, max8MiB')
    offset=8;ihdr=None;compressed=[];ended=False
    while offset+12<=len(raw):
        size=struct.unpack('>I',raw[offset:offset+4])[0];kind=raw[offset+4:offset+8];end=offset+12+size
        if end>len(raw):raise ValueError('Truncated PNG')
        data=raw[offset+8:offset+8+size];crc=struct.unpack('>I',raw[offset+8+size:end])[0]
        if zlib.crc32(kind+data)&0xffffffff!=crc:raise ValueError('PNG checksum mismatch')
        if kind==b'IHDR':
            if ihdr or size!=13:raise ValueError('Invalid PNG header')
            ihdr=struct.unpack('>IIBBBBB',data)
        elif kind==b'IDAT':compressed.append(data)
        elif kind==b'IEND':ended=True;offset=end;break
        offset=end
    if not ihdr or not ended or offset!=len(raw) or not compressed:raise ValueError('Incomplete PNG')
    w,h,depth,color,compression,filtering,interlace=ihdr
    if not (128<=w<=4096 and 128<=h<=4096) or depth!=8 or color not in (0,2,3,4,6) or compression or filtering or interlace:raise ValueError('PNG must be non-interlaced 8-bit, 128–4096px')
    channels={0:1,2:3,3:1,4:2,6:4}[color];stride=w*channels+1;limit=stride*h
    decoder=zlib.decompressobj();decoded=decoder.decompress(b''.join(compressed),limit+1)
    if len(decoded)!=limit or not decoder.eof or decoder.unused_data:raise ValueError('PNG pixel data invalid')
    if any(decoded[y*stride]>4 for y in range(h)):raise ValueError('PNG filter invalid')
    return {'width':w,'height':h,'bytes':len(raw)}
