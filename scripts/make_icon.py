"""生成 App 图标 PNG（纯标准库）：青绿→靛蓝渐变圆角方块 + 白色纸飞机。用法：python3 make_icon.py out.png [size]"""
import struct
import sys
import zlib


def inside_triangle(px, py, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render(n):
    rows = []
    r = n * 0.22  # corner radius
    m = n * 0.06  # margin (macOS icon grid)
    # paper plane in unit coords
    tip, left, tail, fold = (0.78, 0.26), (0.20, 0.50), (0.44, 0.78), (0.47, 0.55)
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            fx, fy = x + 0.5, y + 0.5
            # rounded square mask with 1px anti-alias
            dx = max(m + r - fx, 0, fx - (n - m - r))
            dy = max(m + r - fy, 0, fy - (n - m - r))
            dist = (dx * dx + dy * dy) ** 0.5
            alpha = max(0.0, min(1.0, r - dist + 0.5))
            if fx < m or fx > n - m or fy < m or fy > n - m:
                alpha = 0.0
            t = (fx + fy) / (2 * n)
            cr, cg, cb = (int(20 + (99 - 20) * t), int(184 + (102 - 184) * t), int(166 + (241 - 166) * t))
            u, v = fx / n, fy / n
            if inside_triangle(u, v, tip, left, fold) or inside_triangle(u, v, tip, fold, tail):
                shade = 1.0 if inside_triangle(u, v, tip, left, fold) else 0.86
                cr, cg, cb = int(255 * shade), int(255 * shade), int(255 * shade)
            row += bytes([cr, cg, cb, int(alpha * 255)])
        rows.append(bytes(row))
    raw = zlib.compress(b''.join(rows), 9)

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 6, 0, 0, 0)) + chunk(b'IDAT', raw) + chunk(b'IEND', b'')


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'icon.png'
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 1024
    with open(out, 'wb') as f:
        f.write(render(size))
