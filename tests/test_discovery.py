"""
Unit tests for NetMash discovery payload generation and responder formatting.
"""

import json
from netmash.config import DISCOVERY_SERVICE_NAME
from netmash.discovery.service import DiscoveryResponder


def test_discovery_responder_init():
    responder = DiscoveryResponder(
        node_id="test-node-123",
        host_name="TEST-PC",
        tcp_port=9000,
        discovery_port=9001,
    )
    assert responder.node_id == "test-node-123"
    assert responder.host_name == "TEST-PC"
    assert responder.tcp_port == 9000
    assert responder.discovery_port == 9001
