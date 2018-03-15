#!/usr/bin/python

import math
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.link import Link, Intf, TCLink
from mininet.node import Controller, RemoteController, OVSController
from mininet.cli import CLI
from mininet.util import dumpNodeConnections
from mininet.log import setLogLevel


class FatTreeTopo(Topo):

    def __init__(self, ary=4):
        "Create custom topo."

        # Initialize topology
        Topo.__init__(self)

        self.ary = ary
        self.coreNum = (ary / 2) ** 2
        self.podNum = ary
        self.coreList = []
        self.podList = []

        self.createPods()
        self.createCores()
        self.linkCoresAndPods()

    def createPods(self):
        self.podList = [self.Pod(self, i) for i in range(self.podNum)]

    def createCores(self):
        self.coreList = [self.addSwitch(('c%d' % i)) for i in range(self.coreNum)]

    def linkCoresAndPods(self):
        for (idx, core) in enumerate(self.coreList):
            aggr = int(math.floor(idx / (self.ary / 2)))
            for pod in self.podList:
                self.addLink(core, pod.aggrList[aggr])

    class Pod():
        def __init__(self, topo=None, id=None):
            self.topo = topo
            self.id = id or str(len(topo.podList))
            self.aggrNum = topo.ary / 2
            self.edgeNum = topo.ary / 2
            self.hostNum = (topo.ary / 2) ** 2
            self.edgeList = []
            self.aggrList = []
            self.hostList = []

            self.createSwitches()
            self.createHosts()
            self.linkHostsAndEdges()
            self.linkEdgesAndAggrs()

        def createSwitches(self):
            self.aggrList = [
                self.topo.addSwitch(('aggr-%s-%d') % (self.id, i))
                for i in range(self.aggrNum)
            ]
            self.edgeList = [
                self.topo.addSwitch(('edge-%s-%d') % (self.id, i))
                for i in range(self.edgeNum)
            ]

        def createHosts(self):
            self.hostList = [
                self.topo.addHost(('h-%s-%d') % (self.id, i))
                for i in range(self.hostNum)
            ]

        def linkHostsAndEdges(self):
            for (idx, host) in enumerate(self.hostList):
                edge = int(math.floor(idx / self.edgeNum))
                self.topo.addLink(self.edgeList[edge], host)

        def linkEdgesAndAggrs(self):
            for aggr in self.aggrList:
                for edge in self.edgeList:
                    self.topo.addLink(aggr, edge)


def test():
    topo = FatTreeTopo()

    net = Mininet(topo=topo, link=TCLink, controller=None)
    net.addController('controller', controller=RemoteController, ip='192.168.1.32', port=6653)

    net.start()
    dumpNodeConnections(net.hosts)
    net.pingAll()
    CLI(net)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    test()
