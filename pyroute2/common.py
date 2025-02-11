# -*- coding: utf-8 -*-
'''
Common utilities
'''
import errno
import io
import os
import socket
import struct
import threading
import time
import types
from typing import Any, Callable, Literal, TextIO, TypeVar, Union
from typing_extensions import Self

basestring = (str, bytes)
file = io.BytesIO

AF_MPLS = 28
_uuid32 = 0  # (singleton) the last uuid32 value saved to avoid collisions
_uuid32_lock = threading.Lock()

size_suffixes = {
    'b': 1,
    'k': 1024,
    'kb': 1024,
    'm': 1024 * 1024,
    'mb': 1024 * 1024,
    'g': 1024 * 1024 * 1024,
    'gb': 1024 * 1024 * 1024,
    'kbit': 1024 / 8,
    'mbit': 1024 * 1024 / 8,
    'gbit': 1024 * 1024 * 1024 / 8,
}


time_suffixes = {
    's': 1,
    'sec': 1,
    'secs': 1,
    'ms': 1000,
    'msec': 1000,
    'msecs': 1000,
    'us': 1000000,
    'usec': 1000000,
    'usecs': 1000000,
}

rate_suffixes = {
    'bit': 1,
    'Kibit': 1024,
    'kbit': 1000,
    'mibit': 1024 * 1024,
    'mbit': 1000000,
    'gibit': 1024 * 1024 * 1024,
    'gbit': 1000000000,
    'tibit': 1024 * 1024 * 1024 * 1024,
    'tbit': 1000000000000,
    'Bps': 8,
    'KiBps': 8 * 1024,
    'KBps': 8000,
    'MiBps': 8 * 1024 * 1024,
    'MBps': 8000000,
    'GiBps': 8 * 1024 * 1024 * 1024,
    'GBps': 8000000000,
    'TiBps': 8 * 1024 * 1024 * 1024 * 1024,
    'TBps': 8000000000000,
}


##
# General purpose
#
class Namespace(object):
    def __init__(
        self,
        parent: Self,
        override: Union[dict[str, Any], None] = None
    ):
        self.parent = parent
        self.override = override or {}

    def __getattr__(self, key: str) -> Union[str, types.MethodType]:
        if key in ('parent', 'override'):
            return getattr(self, key)
        elif key in self.override:
            return self.override[key]
        else:
            ret = getattr(self.parent, key)
            # ACHTUNG
            #
            # if the attribute we got with `getattr`
            # is a method, rebind it to the Namespace
            # object, so all subsequent getattrs will
            # go through the Namespace also.
            #
            if isinstance(ret, types.MethodType):
                ret = type(ret)(ret.__func__, self)
            return ret

    def __setattr__(self, key: str, value: int):
        if key in ('parent', 'override'):
            object.__setattr__(self, key, value)
        elif key in self.override:
            self.override[key] = value
        else:
            setattr(self.parent, key, value)


def map_namespace(
    prefix: str,
    ns: dict[str, Any],
    normalize: Union[None, Literal[True], Callable[[str], str]] = None
) -> tuple[dict[str, int], dict[int, str]]:
    '''
    Take the namespace prefix, list all constants and build two
    dictionaries -- straight and reverse mappings. E.g.:

    ## neighbor attributes
    NDA_UNSPEC = 0
    NDA_DST = 1
    NDA_LLADDR = 2
    NDA_CACHEINFO = 3
    NDA_PROBES = 4
    (NDA_NAMES, NDA_VALUES) = map_namespace('NDA', globals())

    Will lead to::

        NDA_NAMES = {'NDA_UNSPEC': 0,
                     ...
                     'NDA_PROBES': 4}
        NDA_VALUES = {0: 'NDA_UNSPEC',
                      ...
                      4: 'NDA_PROBES'}

    The `normalize` parameter can be:

        - None — no name transformation will be done
        - True — cut the prefix and `lower()` the rest
        - lambda x: … — apply the function to every name
    '''
    transform: Callable[[str], str]

    if normalize is None:
        transform = lambda x: x
    elif normalize is True:
        transform = lambda x: x[len(prefix):].lower()
    elif isinstance(normalize, types.FunctionType):
        transform = normalize
    else:
        raise ValueError("Invalid value for `normalize` parameter")

    by_name = {transform(i): ns[i] for i in ns.keys() if i.startswith(prefix)}
    by_value = {ns[i]: transform(i) for i in ns.keys() if i.startswith(prefix)}
    return (by_name, by_value)


def getbroadcast(
    addr: str,
    mask: int,
    family: socket.AddressFamily = socket.AF_INET
) -> str:
    # 1. convert addr to int
    i = socket.inet_pton(family, addr)
    if family == socket.AF_INET:
        i = struct.unpack('>I', i)[0]
        a = 0xFFFFFFFF
        length = 32
    elif family == socket.AF_INET6:
        i = struct.unpack('>QQ', i)
        i = i[0] << 64 | i[1]
        a = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        length = 128
    else:
        raise NotImplementedError('family not supported')
    # 2. calculate mask
    m = (a << length - mask) & a
    # 3. calculate default broadcast
    n = (i & m) | a >> mask
    # 4. convert it back to the normal address form
    if family == socket.AF_INET:
        n = struct.pack('>I', n)
    else:
        n = struct.pack('>QQ', n >> 64, n & (a >> 64))
    return socket.inet_ntop(family, n)


def dqn2int(mask: str, family: socket.AddressFamily = socket.AF_INET) -> int:
    '''
    IPv4 dotted quad notation to int mask conversion
    '''
    ret = 0
    binary = socket.inet_pton(family, mask)
    for offset in range(len(binary) // 4):
        ret += bin(
            struct.unpack('I', binary[offset * 4 : offset * 4 + 4])[0]
        ).count('1')
    return ret


def get_address_family(address: str) -> socket.AddressFamily:
    if address.find(':') > -1:
        return socket.AF_INET6
    else:
        return socket.AF_INET


def hexdump(payload: bytes, length: int = 0) -> str:
    '''
    Represent byte string as hex -- for debug purposes
    '''
    return ':'.join('{0:02x}'.format(c) for c in payload[:length] or payload)


def load_dump(
    f: Union[str, TextIO],
    meta: Union[dict[str, str], None] = None
) -> Union[bytes, str]:
    '''
    Load a packet dump from an open file-like object or a string.

    Supported dump formats:

    * strace hex dump (\\x00\\x00...)
    * pyroute2 hex dump (00:00:...)

    Simple markup is also supported. Any data from # or ;
    till the end of the string is a comment and ignored.
    Any data after . till EOF is ignored as well.

    With #! starts an optional code block. All the data
    in the code block will be read and returned via
    metadata dictionary.
    '''
    data = ''
    code = None
    meta_data = None
    meta_label = None
    if isinstance(f, str):
        io_obj = io.StringIO()
        io_obj.write(f)
        io_obj.seek(0)
    else:
        io_obj = f

    for a in io_obj.readlines():
        if code is not None:
            code += a
            continue

        if meta_data is not None:
            meta_data += a
            continue

        offset = 0
        length = len(a)
        while offset < length:
            if a[offset] in (' ', '\t', '\n'):
                offset += 1
            elif a[offset] == '#':
                if a[offset : offset + 2] == '#!':
                    # read the code block until EOF
                    code = ''
                elif a[offset : offset + 2] == '#:':
                    # read data block until EOF
                    meta_label = a.split(':')[1].strip()
                    meta_data = ''
                break
            elif a[offset] == '.':
                return data
            elif a[offset] == '\\':
                # strace hex format
                data += chr(int(a[offset + 2 : offset + 4], 16))
                offset += 4
            else:
                # pyroute2 hex format
                data += chr(int(a[offset : offset + 2], 16))
                offset += 3

    if isinstance(meta, dict):
        if code is not None:
            meta['code'] = code
        if meta_data is not None and meta_label is not None:
            meta[meta_label] = meta_data

    return bytes(data, 'iso8859-1')


class AddrPool(object):
    '''
    Address pool
    '''

    cell = 0xFFFFFFFFFFFFFFFF

    def __init__(
        self,
        minaddr: int = 0xF,
        maxaddr: int = 0xFFFFFF,
        reverse: bool = False,
        release: bool = False
    ):
        self.cell_size = 0  # in bits
        mx = self.cell
        self.reverse = reverse
        self.release = release
        self.ban: list[dict[str, int]] = []
        while mx:
            mx >>= 8
            self.cell_size += 1
        self.cell_size *= 8
        # calculate, how many ints we need to bitmap all addresses
        self.cells = int((maxaddr - minaddr) / self.cell_size + 1)
        # initial array
        self.addr_map = [self.cell]
        self.minaddr = minaddr
        self.maxaddr = maxaddr
        self.lock = threading.RLock()

    def alloc(self) -> int:
        with self.lock:
            # gc self.ban:
            for item in tuple(self.ban):
                if item['counter'] == 0:
                    self.free(item['addr'])
                    self.ban.remove(item)
                else:
                    item['counter'] -= 1

            # iterate through addr_map
            base = 0
            for cell in self.addr_map:
                if cell:
                    # not allocated addr
                    bit = 0
                    while True:
                        if (1 << bit) & self.addr_map[base]:
                            self.addr_map[base] ^= 1 << bit
                            break
                        bit += 1
                    ret = base * self.cell_size + bit

                    if self.reverse:
                        ret = self.maxaddr - ret
                    else:
                        ret = ret + self.minaddr

                    if self.minaddr <= ret <= self.maxaddr:
                        if self.release:
                            self.free(ret, ban=self.release)
                        return ret
                    else:
                        self.free(ret)
                        raise KeyError('no free address available')

                base += 1
            # no free address available
            if len(self.addr_map) < self.cells:
                # create new cell to allocate address from
                self.addr_map.append(self.cell)
                return self.alloc()
            else:
                raise KeyError('no free address available')

    def locate(self, addr: int) -> tuple[int, int, bool]:
        if self.reverse:
            addr = self.maxaddr - addr
        else:
            addr -= self.minaddr
        base = addr // self.cell_size
        bit = addr % self.cell_size
        try:
            is_allocated = not self.addr_map[base] & (1 << bit)
        except IndexError:
            is_allocated = False
        return (base, bit, is_allocated)

    def free(self, addr: int, ban: int = 0):
        with self.lock:
            if ban != 0:
                self.ban.append({'addr': addr, 'counter': ban})
            else:
                base, bit, _ = self.locate(addr)
                if len(self.addr_map) <= base:
                    raise KeyError('address is not allocated')
                if self.addr_map[base] & (1 << bit):
                    raise KeyError('address is not allocated')
                self.addr_map[base] ^= 1 << bit


def fnv1(data: bytes) -> int:
    '''
    FNV1 -- 32bit hash, python3 version

    Returns: 32bit int hash

    See: http://www.isthe.com/chongo/tech/comp/fnv/index.html
    '''
    hval = 0x811C9DC5
    for i in range(len(data)):
        hval *= 0x01000193
        hval ^= data[i]
    return hval & 0xFFFFFFFF


def uuid32() -> int:
    '''
    Return 32bit UUID, based on the current time and pid.

    The uuid is guaranteed to be unique within one process.
    '''
    global _uuid32
    global _uuid32_lock

    with _uuid32_lock:
        candidate = _uuid32
        while candidate == _uuid32:
            candidate = fnv1(
                struct.pack('QQ', int(time.time() * 1000000), os.getpid())
            )
        _uuid32 = candidate
        return candidate


def uifname() -> str:
    '''
    Return a unique interface name based on a prime function
    '''
    return 'pr%x' % uuid32()


F = TypeVar("F", bound=Callable[..., Any])

def map_exception(
    match: Callable[[Exception], bool],
    subst: Callable[[Exception], Exception]
) -> Callable[[F], F]:
    '''
    Decorator to map exception types
    '''

    def wrapper(f: F) -> F:
        def decorated(*argv: Any, **kwarg: Any) -> Any:
            try:
                f(*argv, **kwarg)
            except Exception as e:
                if match(e):
                    raise subst(e)
                raise

        return decorated  # type: ignore

    return wrapper


def map_enoent(f: F) -> F:
    '''
    Shortcut to map OSError(2) -> OSError(95)
    '''
    return map_exception(
        lambda x: (isinstance(x, OSError) and x.errno == errno.ENOENT),
        lambda x: OSError(errno.EOPNOTSUPP, 'Operation not supported'),
    )(f)


T = TypeVar('T', bound=Callable[..., Any])

def metaclass(mc: T) -> Callable[..., T]:
    def wrapped(cls: T) -> T:
        nvars = {}
        skip = ['__dict__', '__weakref__']
        slots = cls.__dict__.get('__slots__')
        if not isinstance(slots, (list, tuple)):
            slots = [slots]
        for k in slots:
            skip.append(k)
        for k, v in cls.__dict__.items():
            if k not in skip:
                nvars[k] = v
        return mc(cls.__name__, cls.__bases__, nvars)

    return wrapped


def msg_done(msg: ...) -> bytes:
    newmsg = struct.pack('IHH', 40, 2, 0)
    newmsg += msg.data[8:16]
    newmsg += struct.pack('I', 0)
    # nlmsgerr struct alignment
    newmsg += b'\0' * 20
    return newmsg
