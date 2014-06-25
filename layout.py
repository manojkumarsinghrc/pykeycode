#!/usr/bin/env python
# http://stackoverflow.com/questions/1918841/how-to-convert-ascii-character-to-cgkeycode */

import ctypes
import ctypes.util
import struct
import CoreFoundation
import Foundation
import objc

try:
    unichr
except NameError:
    unichr = chr

carbon_path = ctypes.util.find_library('Carbon')
carbon = ctypes.cdll.LoadLibrary(carbon_path)
    
# We could rely on the fact that kTISPropertyUnicodeKeyLayoutData has
# been the string @"TISPropertyUnicodeKeyLayoutData" since even the
# Classic Mac days. Or we could load it from the framework. 
# Unfortunately, the framework doesn't have PyObjC wrappers, and there's
# no easy way to force PyObjC to wrap a CF/ObjC object that it doesn't
# know about. So:
_objc = ctypes.PyDLL(objc._objc.__file__)
_objc.PyObjCObject_New.restype = ctypes.py_object
_objc.PyObjCObject_New.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
def objcify(ptr):
    return _objc.PyObjCObject_New(ptr, 0, 1)
kTISPropertyUnicodeKeyLayoutData_p = ctypes.c_void_p.in_dll(
    carbon, 'kTISPropertyUnicodeKeyLayoutData')
kTISPropertyUnicodeKeyLayoutData = objcify(kTISPropertyUnicodeKeyLayoutData_p)

OptionBits = ctypes.c_uint32
UniCharCount = ctypes.c_uint8
UniChar = ctypes.c_uint16
UniChar4 = UniChar * 4

ByteOffset = ctypes.c_uint32
ItemCount = ctypes.c_uint32

class UCKeyboardTypeHeader(ctypes.Structure):
    _fields_ = [('keyboardTypeFirst', ctypes.c_uint32),
                ('keyboardTypeLast', ctypes.c_uint32),
                ('keyModifiersToTableNumOffset', ByteOffset),
                ('keyToCharTableIndexOffset', ByteOffset),
                ('keyStateRecordsIndexOffset', ByteOffset),
                ('keyStateTerminatorsOffset', ByteOffset),
                ('keySequenceDataIndexOffset', ByteOffset)]

class UCKeyboardLayout(ctypes.Structure):
    _fields_ = [('keyLayoutHeaderFormat', ctypes.c_uint16),
                ('keyLayoutDataVersion', ctypes.c_uint16),
                ('keyLayoutFeatureInfoOffset', ByteOffset),
                ('keyboardTypeCount', ItemCount),
                ('keyboardTypeList', UCKeyboardTypeHeader*1)]

class UCKeyLayoutFeatureInfo(ctypes.Structure):
    _fields_ = [('keyLayoutFeatureInfoFormat', ctypes.c_uint16),
                ('reserved', ctypes.c_uint16),
                ('maxOutputStringLength', UniCharCount)]

class UCKeyModifiersToTableNum(ctypes.Structure):
    _fields_ = [('keyModifiersToTableNumFormat', ctypes.c_uint16),
                ('defaultTableNum', ctypes.c_uint16),
                ('modifiersCount', ItemCount),
                ('tableNum', ctypes.c_uint8*1)]

class UCKeyToCharTableIndex(ctypes.Structure):
    _fields_ = [('keyToCharTableIndexFormat', ctypes.c_uint16),
                ('keyToCharTableSize', ctypes.c_uint16),
                ('keyToCharTableCount', ItemCount),
                ('keyToCharTableOffsets', ByteOffset*1)]
        
CFIndex = ctypes.c_int64
class CFRange(ctypes.Structure):
    _fields_ = [('loc', CFIndex),
                ('len', CFIndex)]

carbon.TISCopyCurrentKeyboardInputSource.argtypes = []
carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
carbon.LMGetKbdType.argtypes = []
carbon.LMGetKbdType.restype = ctypes.c_uint32
carbon.CFDataGetLength.argtypes = [ctypes.c_void_p]
carbon.CFDataGetLength.restype = ctypes.c_uint64
carbon.CFDataGetBytes.argtypes = [ctypes.c_void_p, CFRange, ctypes.c_void_p]
carbon.CFDataGetBytes.restype = None

kTISPropertyUnicodeKeyLayoutData = ctypes.c_void_p.in_dll(
    carbon, 'kTISPropertyUnicodeKeyLayoutData')

def parselayout(buf, ktype):
    hf, dv, featureinfo, ktcount = struct.unpack_from('HHII', buf)
    offset = struct.calcsize('HHII')
    ktsize = struct.calcsize('IIIIIII')
    kts = [struct.unpack_from('IIIIIII', buf, offset+ktsize*i)
           for i in range(ktcount)]
    for i, kt in enumerate(kts):
        if kt[0] <= ktype <= kt[1]:
            kentry = i
            break
    else:
        kentry = 0
    ktf, ktl, modoff, charoff, sroff, stoff, seqoff = kts[kentry]
    #for i, kt in enumerate(kts):
    #    print('{:3}-{:3}{} mods {} char {} records {} term {} seq {}'.format(
    #        kt[0], kt[1], 
    #        '*' if i == kentry else ' ',
    #        kt[2], kt[3], kt[4], kt[5], kt[6]))

    # Modifiers
    mf, deftable, mcount = struct.unpack_from('HHI', buf, modoff)
    modtableoff = modoff + struct.calcsize('HHI')
    modtables = struct.unpack_from('B'*mcount, buf, modtableoff)
    modmapping = {}
    for i, table in enumerate(modtables):
        modmapping.setdefault(table, i)
    #print(modmapping)

    # Sequences
    if not seqoff:
        sequences = []
    else:
        sf, scount = struct.unpack_from('HH', buf, seqoff)
        seqtableoff = seqoff + struct.calcsize('HH')
        lastsoff = -1
        for soff in struct.unpack_from('H'*scount, buf, seqtableoff):
            if lastsoff >= 0:
                sequences.append(buf[seqoff+lastoff:seqoff+soff].decode('utf-16'))
            lastsoff = soff
    def lookupseq(key):
        if key >= 0xFFFE:
            return None
        if key & 0xC000:
            seq = key & ~0xC000
            if seq < len(sequences):
                return sequences[seq]
        return unichr(key)

    # Dead keys
    deadkeys = []
    if sroff:
        srf, srcount = struct.unpack_from('HH', buf, sroff)
        srtableoff = sroff + struct.calcsize('HH')
        for recoff in struct.unpack_from('I'*srcount, buf, srtableoff):
            cdata, nextstate, ecount, eformat = struct.unpack_from('HHHH', buf, recoff)
            recdataoff = recoff + struct.calcsize('HHHH')
            edata = buf[recdataoff:recdataoff+4*ecount]
            deadkeys.append((cdata, nextstate, ecount, eformat, edata))
    #for dk in deadkeys:
    #    print(dk)
    if stoff:
        stf, stcount = struct.unpack_from('HH', buf, stoff)
        sttableoff = stoff + struct.calcsize('HH')
        dkterms = struct.unpack_from('H'*stcount, buf, sttableoff)
    else:
        dkterms = []
    #print(dkterms)

    def lookup_and_add(key, j, mod):
        ch = lookupseq(key)
        if ch is not None:
            mapping.setdefault(ch, (j, mod))
            revmapping[j, mod] = ch
        elif key == 0xFFFF:
            revmapping[j, mod] = ''
        else:
            revmapping[j, mod] = '<{}>'.format(key)
    
    # Get char tables
    cf, csize, ccount = struct.unpack_from('HHI', buf, charoff)
    chartableoff = charoff + struct.calcsize('HHI')
    mapping = {}
    revmapping = {}
    deadstatemapping = {}
    deadrevmapping = {}
    for i, tableoff in enumerate(struct.unpack_from('I'*ccount, buf, chartableoff)):
        mod = modmapping[i]
        for j, key in enumerate(struct.unpack_from('H'*csize, buf, tableoff)):
            ch = None
            if key >= 0xFFFE:
                revmapping[j, mod] = '<{}>'.format(key)
            elif key & 0x0C000 == 0x4000:
                dead = key & ~0xC000
                if dead < len(deadkeys):
                    cdata, nextstate, ecount, eformat, edata = deadkeys[dead]
                    if eformat == 0 and nextstate: # initial
                        deadstatemapping[nextstate] = (j, mod)
                        if nextstate-1 < len(dkterms):
                            basekey = lookupseq(dkterms[nextstate-1])
                            revmapping[j, mod] = '<deadkey #{}: {}>'.format(nextstate, basekey)
                        else:
                            revmapping[j, mod] = '<deadkey #{}>'.format(nextstate)
                    elif eformat == 1: # terminal
                        deadrevmapping[j, mod] = deadkeys[dead]
                        lookup_and_add(cdata, j, mod)
                    elif eformat == 2: # range
                        # TODO!
                        pass
            else:
                lookup_and_add(key, j, mod)
                
    for key, dead in deadrevmapping.items():
        j, mod = key
        cdata, nextstate, ecount, eformat, edata = dead
        entries = [struct.unpack_from('HH', edata, i*4) for i in range(ecount)]
        for state, key in entries:
            dj, dmod = deadstatemapping[state]
            ch = lookupseq(key)
            mapping.setdefault(ch, ((dj, dmod), (j, mod)))
            revmapping[(dj, dmod), (j, mod)] = ch

    return mapping, revmapping, modmapping

def getlayout():
    keyboard_p = carbon.TISCopyCurrentKeyboardInputSource()
    keyboard = objcify(keyboard_p)
    layout_p = carbon.TISGetInputSourceProperty(keyboard_p, 
                                                kTISPropertyUnicodeKeyLayoutData)
    layout_size = carbon.CFDataGetLength(layout_p)
    layout_buf = ctypes.create_string_buffer(b'\000'*layout_size)
    carbon.CFDataGetBytes(layout_p, CFRange(0, layout_size), ctypes.byref(layout_buf))
    ktype = carbon.LMGetKbdType()
    ret = parselayout(layout_buf, ktype)
    CoreFoundation.CFRelease(keyboard)
    return ret

mapping, revmapping, modmapping = getlayout()

def modstr(mod):
    s = ''
    if mod & 16:
        s = 'C-' + s
    if mod & 8:
        s = 'O-' + s
    if mod & 4:
        s = 'L-' + s
    if mod & 2:
        s = 'S-' + s
    if mod & 1:
        s = '?-' + s
    return s

def printify(s):
    return s if s.isprintable() else s.encode('unicode_escape').decode('utf-8')

def printcode(keycode):
    keys = ('{}:{}'.format(modstr(mod).rstrip('-'),
                           printify(revmapping[keycode, mod]))
            for mod in sorted(modmapping.values()))
    print(u"{:3} {}".format(keycode, ' '.join(keys)))

if __name__ == '__main__':
    import sys
    for arg in sys.argv[1:]:
        try:
            arg = arg.decode(sys.stdin.encoding)
        except AttributeError:
            pass
        try:
            keycode = int(arg)
        except ValueError:
            for ch in arg:
                result = mapping.get(ch, (None, 0))
                if result is None or result[0] is None:
                    print(u"{}: not found".format(printify(ch)))
                else:
                    if not isinstance(result[0], tuple):
                        result = result,
                    print(u"{}: {}".format(printify(ch),
                                           ', '.join('{}{}'.format(modstr(mod), keycode)
                                                     for keycode, mod in result)))
        else:
            printcode(keycode)
    if len(sys.argv) < 2:
        for keycode in range(127):
            printcode(keycode)