import struct
from socket import AF_ROUTE
from socket import SOCK_RAW
from socket import AF_INET
from socket import AF_INET6
from pyroute2 import config
from pyroute2.bsd.pf_route import (bsdmsg,
                                   if_msg,
                                   rt_msg,
                                   if_announcemsg,
                                   ifma_msg,
                                   ifa_msg)

from pyroute2.netlink.rtnl.ifaddrmsg import ifaddrmsg
from pyroute2.netlink.rtnl.ifinfmsg import ifinfmsg
from pyroute2.netlink.rtnl.rtmsg import rtmsg
from pyroute2.netlink.rtnl import (RTM_NEWLINK as RTNL_NEWLINK,
                                   RTM_DELLINK as RTNL_DELLINK,
                                   RTM_NEWADDR as RTNL_NEWADDR,
                                   RTM_DELADDR as RTNL_DELADDR,
                                   RTM_NEWROUTE as RTNL_NEWROUTE,
                                   RTM_DELROUTE as RTNL_DELROUTE)

RTM_ADD = 0x1          # Add Route
RTM_DELETE = 0x2       # Delete Route
RTM_CHANGE = 0x3       # Change Metrics or flags
RTM_GET = 0x4          # Report Metrics
RTM_LOSING = 0x5       # Kernel Suspects Partitioning
RTM_REDIRECT = 0x6     # Told to use different route
RTM_MISS = 0x7         # Lookup failed on this address
RTM_LOCK = 0x8         # Fix specified metrics
RTM_RESOLVE = 0xb      # Req to resolve dst to LL addr
RTM_NEWADDR = 0xc      # Address being added to iface
RTM_DELADDR = 0xd      # Address being removed from iface
RTM_IFINFO = 0xe       # Iface going up/down etc
RTM_IFANNOUNCE = 0xf   # Iface arrival/departure
RTM_DESYNC = 0x10      # route socket buffer overflow
RTM_INVALIDATE = 0x10  # Invalidate cache of L2 route
RTM_BFD = 0x12         # bidirectional forwarding detection
RTM_PROPOSAL = 0x13    # proposal for netconfigd


def convert_rt_msg(msg):
    ret = rtmsg()
    ret['header']['type'] = RTNL_NEWROUTE if \
        msg['header']['type'] == RTM_ADD else \
        RTNL_DELROUTE
    ret['family'] = msg['DST']['header']['family']
    ret['attrs'] = []
    if 'NETMASK' in msg and \
            msg['NETMASK']['header']['family'] == ret['family']:
        ret['dst_len'] = 0  # FIXME!!!
    if 'GATEWAY' in msg:
        if msg['GATEWAY']['header']['family'] not in (AF_INET, AF_INET6):
            # interface routes, table 255
            # discard for now
            return None
        ret['attrs'].append(['RTA_DST', msg['GATEWAY']['address']])
    if 'IFA' in msg:
        ret['attrs'].append(['RTA_SRC', msg['IFA']['address']])
    if 'IFP' in msg:
        ret['attrs'].append(['RTA_OIF', msg['IFP']['index']])
    del ret['value']
    return ret


def convert_if_msg(msg):
    # discard this type for now
    return None


def convert_ifa_msg(msg):
    ret = ifaddrmsg()
    ret['header']['type'] = RTNL_NEWADDR if \
        msg['header']['type'] == RTM_NEWADDR else \
        RTNL_DELADDR
    ret['index'] = msg['IFP']['index']
    ret['prefixlen'] = 0  # FIXME!!!
    ret['family'] = msg['IFA']['header']['family']
    ret['attrs'] = [['IFA_ADDRESS', msg['IFA']['address']],
                    ['IFA_BROADCAST', msg['BRD']['address']],
                    ['IFA_LABEL', msg['IFP']['ifname']]]
    del ret['value']
    return ret


def convert_ifma_msg(msg):
    # ignore for now
    return None


def convert_if_announcemsg(msg):
    ret = ifinfmsg()
    ret['header']['type'] = RTNL_DELLINK if msg['ifan_what'] else RTNL_NEWLINK
    ret['index'] = msg['ifan_index']
    ret['attrs'] = [['IFLA_IFNAME', msg['ifan_name']]]
    del ret['value']
    return ret


convert = {rt_msg: convert_rt_msg,
           ifa_msg: convert_ifa_msg,
           if_msg: convert_if_msg,
           ifma_msg: convert_ifma_msg,
           if_announcemsg: convert_if_announcemsg}


class RTMSocket(object):

    msg_map = {RTM_ADD: rt_msg,
               RTM_DELETE: rt_msg,
               RTM_CHANGE: rt_msg,
               RTM_GET: rt_msg,
               RTM_LOSING: rt_msg,
               RTM_REDIRECT: rt_msg,
               RTM_MISS: rt_msg,
               RTM_LOCK: rt_msg,
               RTM_RESOLVE: rt_msg,
               RTM_NEWADDR: ifa_msg,
               RTM_DELADDR: ifa_msg,
               RTM_IFINFO: if_msg,
               RTM_IFANNOUNCE: if_announcemsg,
               RTM_DESYNC: bsdmsg,
               RTM_INVALIDATE: bsdmsg,
               RTM_BFD: bsdmsg,
               RTM_PROPOSAL: bsdmsg}

    def __init__(self, output='pf_route'):
        self._sock = config.SocketBase(AF_ROUTE, SOCK_RAW)
        self._output = output

    def fileno(self):
        return self._sock.fileno()

    def get(self):
        msg = self._sock.recv(2048)
        from pyroute2.common import hexdump
        print(hexdump(msg))
        _, _, msg_type = struct.unpack('HBB', msg[:4])
        msg_class = self.msg_map.get(msg_type, None)
        if msg_class is not None:
            msg = msg_class(msg)
            msg.decode()
            if self._output == 'netlink':
                # convert messages to the Netlink format
                msg = convert[type(msg)](msg)
        return msg
