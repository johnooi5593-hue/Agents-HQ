"""Removes initializers from an ONNX graph's input list (no weights change), so onnxruntime can fold and pre-pack them.

usage: python onnx_strip_inputs.py <in.onnx> <out.onnx>

Why: the UltraFace RFB-640 export lists every weight as a graph input too. onnxruntime then treats the weights as
values that may change on each run ("Initializer ... appears in graph inputs and will not be treated as constant"),
which made one 640x480 inference take ~155 ms here. This edits the protobuf wire format directly (the onnx package
is not installed): ModelProto.graph (field 7) -> GraphProto.input (field 11) entries whose name (field 1) is also an
initializer (field 5, TensorProto.name = field 8) are dropped. Everything else is copied byte for byte.
Prints one JSON line.
"""
import hashlib, json, sys


def varint(buf, i):
    v = s = 0
    while True:
        b = buf[i]; i += 1
        v |= (b & 0x7F) << s; s += 7
        if b < 0x80:
            return v, i


def enc_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F; v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b); return bytes(out)


def fields(buf):
    """Yields (field number, wire type, raw bytes of the whole field, payload start, payload end)."""
    i, n = 0, len(buf)
    while i < n:
        st = i
        key, i = varint(buf, i)
        fn, wt = key >> 3, key & 7
        if wt == 0:
            ps = i; _, i = varint(buf, i); pe = i
        elif wt == 1:
            ps, i = i, i + 8; pe = i
        elif wt == 2:
            ln, i = varint(buf, i); ps, pe = i, i + ln; i = pe
        elif wt == 5:
            ps, i = i, i + 4; pe = i
        else:
            raise ValueError(f'unsupported wire type {wt}')
        yield fn, wt, buf[st:i], ps, pe


def name_of(msg, field):
    for fn, wt, raw, ps, pe in fields(msg):
        if fn == field and wt == 2:
            return msg[ps:pe].decode('utf-8', 'replace')
    return None


def strip(model):
    out, dropped = bytearray(), 0
    for fn, wt, raw, ps, pe in fields(model):
        if fn != 7:
            out += raw; continue
        g = model[ps:pe]
        inits = {name_of(g[a:b], 8) for f2, w2, r2, a, b in fields(g) if f2 == 5}
        ng = bytearray()
        for f2, w2, r2, a, b in fields(g):
            if f2 == 11 and name_of(g[a:b], 1) in inits:
                dropped += 1; continue
            ng += r2
        out += enc_varint((7 << 3) | 2) + enc_varint(len(ng)) + ng
    return bytes(out), dropped


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src = open(sys.argv[1], 'rb').read()
    res, dropped = strip(src)
    with open(sys.argv[2], 'wb') as f:
        f.write(res)
    print(json.dumps({'ok': True, 'out': sys.argv[2], 'inputs_dropped': dropped, 'bytes': len(res),
                      'sha256': hashlib.sha256(res).hexdigest(), 'source_sha256': hashlib.sha256(src).hexdigest()}))


if __name__ == '__main__':
    main()
