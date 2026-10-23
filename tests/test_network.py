from phone_pad.network import address_options


def test_prefers_default_route_and_excludes_virtual_and_loopback():
    interfaces = [
        {"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "family": "inet"}]},
        {"ifname": "docker0", "addr_info": [{"local": "172.17.0.1", "family": "inet"}]},
        {"ifname": "enp1s0", "addr_info": [{"local": "192.168.1.3", "family": "inet"}]},
        {"ifname": "wlp2s0", "addr_info": [{"local": "10.0.0.5", "family": "inet"}]},
    ]
    assert address_options(interfaces, "wlp2s0") == [
        ("wlp2s0 · 10.0.0.5", "10.0.0.5"), ("enp1s0 · 192.168.1.3", "192.168.1.3")]


def test_no_network_does_not_advertise_loopback_as_phone_address():
    assert address_options([], "") == []
