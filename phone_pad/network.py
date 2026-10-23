"""Discover candidate LAN interfaces without contacting an external service."""

import asyncio
import ipaddress
import json


def address_options(interfaces, default_device=""):
    result = []
    seen = set()
    for interface in interfaces:
        name = interface.get("ifname", "")
        if name == "lo" or name.startswith(("docker", "veth", "br-", "virbr", "tun", "tap", "tailscale", "wg")):
            continue
        for address in interface.get("addr_info", []):
            if address.get("family") != "inet":
                continue
            value = address.get("local", "")
            try:
                ip = ipaddress.IPv4Address(value)
            except ipaddress.AddressValueError:
                continue
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast or not ip.is_private or value in seen:
                continue
            seen.add(value)
            result.append((name, value))
    result.sort(key=lambda item: (item[0] != default_device, item[0], item[1]))
    return [(f"{name} · {value}", value) for name, value in result]


async def discover_addresses():
    async def read(*args):
        process = await asyncio.create_subprocess_exec("ip", "-j", "-4", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=3)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("無法讀取網路介面")
        return json.loads(output)

    interfaces, routes = await asyncio.gather(read("address", "show", "up"), read("route", "show", "default"))
    device = min(routes, key=lambda route: route.get("metric", 0)).get("dev", "") if routes else ""
    return address_options(interfaces, device)
