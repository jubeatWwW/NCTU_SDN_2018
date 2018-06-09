# Copyright (C) 2016 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import dpid as dpid_lib
from ryu.lib import stplib
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp
from ryu.lib.packet import arp
from ryu.app import simple_switch_13
import re

class SimpleSwitch13(simple_switch_13.SimpleSwitch13):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'stplib': stplib.Stp}

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.stp = kwargs['stplib']
        self.ip_to_mac = {}
        self.ip_to_port = {}
        self.user_to_ip = {}

        # Sample of stplib config.
        #  please refer to stplib.Stp.set_config() for details.
        config = {dpid_lib.str_to_dpid('0000000000000001'):
                  {'bridge': {'priority': 0x8000}},
                  dpid_lib.str_to_dpid('0000000000000002'):
                  {'bridge': {'priority': 0x9000}},
                  dpid_lib.str_to_dpid('0000000000000003'):
                  {'bridge': {'priority': 0xa000}}}
        self.stp.set_config(config)

    def delete_flow(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        for dst in self.mac_to_port[datapath.id].keys():
            match = parser.OFPMatch(eth_dst=dst)
            mod = parser.OFPFlowMod(
                datapath, command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
                priority=1, match=match)
            datapath.send_msg(mod)

    @set_ev_cls(stplib.EventPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        ip = pkt.get_protocols(ipv4.ipv4)
        tcpp = pkt.get_protocols(tcp.tcp)
        arpp = pkt.get_protocols(arp.arp)
        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.ip_to_port.setdefault(dpid, {})

        if arpp:
            print(arpp[0].src_mac, arpp[0].dst_mac, arpp[0].src_ip, arpp[0].dst_ip)
            if not arpp[0].src_ip in self.ip_to_mac and arpp[0].src_mac != '00:00:00:00:00:00':
                self.ip_to_mac[arpp[0].src_ip] = arpp[0].src_mac
            if not arpp[0].src_ip in self.ip_to_port[dpid]:
                self.ip_to_port[dpid][arpp[0].src_ip] = in_port

        print(self.ip_to_mac)
        print(self.ip_to_port)

        if ip and tcpp:
            # This packet is sent by Auth server
            id = str(tcpp[0].dst_port)
            if ip[0].dst == '10.0.0.87' and tcpp[0].src_port == 1234:
                pattern = re.compile("^" + id + " (.*)")
                for i, line in enumerate(open('memberip')):
                    for match in re.finditer(pattern, line):
                        if ip[0].src in self.user_to_ip:
                            self.user_to_ip[ip[0].src].append(match.groups()[0])
                        else:
                            self.user_to_ip[ip[0].src] = [match.groups()[0]]
                print(self.user_to_ip)

            # if is login user, add meter
            if ip[0].dst in self.user_to_ip:
                print('add meter')
                bands = [parser.OFPMeterBandDrop(
                    type_=ofproto.OFPMBT_DROP,
                    len_=0,
                    rate=100,
                    burst_size=10
                )]
                req = parser.OFPMeterMod(
                    datapath=datapath,
                    command=ofproto.OFPMC_ADD,
                    flags=ofproto.OFPMF_KBPS,
                    meter_id=1,
                    bands=bands
                )
                datapath.send_msg(req)

                match = parser.OFPMatch(in_port=in_port, ipv4_dst=ip[0].dst)
                actions = [parser.OFPActionOutput(self.ip_to_port[dpid][ip[0].dst])]
                inst = [
                    parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions),
                    parser.OFPInstructionMeter(1, ofproto.OFPIT_METER)
                ]
                datapath.send_msg(datapath.ofproto_parser.OFPFlowMod(
                    datapath=datapath,
                    match=match,
                    command=ofproto.OFPFC_ADD,
                    idle_timeout=3000,
                    priority=2,
                    instructions=inst
                ))

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    @set_ev_cls(stplib.EventTopologyChange, MAIN_DISPATCHER)
    def _topology_change_handler(self, ev):
        dp = ev.dp
        dpid_str = dpid_lib.dpid_to_str(dp.id)
        msg = 'Receive topology change event. Flush MAC table.'
        self.logger.debug("[dpid=%s] %s", dpid_str, msg)

        if dp.id in self.mac_to_port:
            self.delete_flow(dp)
            del self.mac_to_port[dp.id]

    @set_ev_cls(stplib.EventPortStateChange, MAIN_DISPATCHER)
    def _port_state_change_handler(self, ev):
        dpid_str = dpid_lib.dpid_to_str(ev.dp.id)
        of_state = {stplib.PORT_STATE_DISABLE: 'DISABLE',
                    stplib.PORT_STATE_BLOCK: 'BLOCK',
                    stplib.PORT_STATE_LISTEN: 'LISTEN',
                    stplib.PORT_STATE_LEARN: 'LEARN',
                    stplib.PORT_STATE_FORWARD: 'FORWARD'}
        self.logger.debug("[dpid=%s][port=%d] state=%s",
                          dpid_str, ev.port_no, of_state[ev.port_state])
