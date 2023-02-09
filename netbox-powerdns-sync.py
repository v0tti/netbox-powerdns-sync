#!/usr/bin/env python3

import ipaddress
import re
import sys

import powerdns
import pynetbox

from config import NB_URL, NB_TOKEN, PDNS_API_URL, PDNS_KEY
from config import FORWARD_ZONES, REVERSE_ZONES, DRY_RUN
from config import SOURCE_DEVICE, SOURCE_IP, SOURCE_VM

nb = pynetbox.api(NB_URL, token=NB_TOKEN)

pdns_api_client = powerdns.PDNSApiClient(api_endpoint=PDNS_API_URL,
                                         api_key=PDNS_KEY)
pdns = powerdns.PDNSEndpoint(pdns_api_client).servers[0]

host_ips = []
record_ips = []
for forward_zone in FORWARD_ZONES:
    forward_zone_canonical = forward_zone+"."

    # Source IP: Create domains based on DNS name attached to IPs
    if SOURCE_IP:
        # get IPs with DNS name ending in forward_zone from NetBox
        nb_ips = nb.ipam.ip_addresses.filter(dns_name__iew=forward_zone)

        # assemble list with tupels containing the canonical name, the record
        # type and the IP address without the subnet from NetBox IPs
        for nb_ip in nb_ips:
            if nb_ip.family.value == 6:
                type = "AAAA"
            else:
                type = "A"
            host_ips.append((
                nb_ip.dns_name+".",
                type,
                re.sub("/[0-9]*", "", str(nb_ip)),
                forward_zone_canonical
            ))

    # Source device: Create domains based on the name of devices
    if SOURCE_DEVICE:
        # get devices with name ending in forward_zone from NetBox
        nb_devices = nb.dcim.devices.filter(name__iew=forward_zone)

        # assemble list with tupels containing the canonical name, the record
        # type and the IP addresses without the subnet of the device
        for nb_device in nb_devices:
            if nb_device.primary_ip4:
                host_ips.append((
                    nb_device.name+".",
                    "A",
                    re.sub("/[0-9]*", "", str(nb_device.primary_ip4)),
                    forward_zone_canonical
                ))
            if nb_device.primary_ip6:
                host_ips.append((
                    nb_device.name+".",
                    "AAAA",
                    re.sub("/[0-9]*", "", str(nb_device.primary_ip6)),
                    forward_zone_canonical
                ))

    # Source VM: Create domains based on the name of VMs
    if SOURCE_VM:
        # get VMs with name ending in forward_zone from NetBox
        nb_vms = nb.virtualization.virtual_machines.filter(
            name__iew=forward_zone)

        # assemble a list with tupels containing the canonical name, the record
        # type and the primary IP addresses without the subnet of the VM
        for nb_vm in nb_vms:
            if nb_vm.primary_ip4:
                host_ips.append((
                    nb_vm.name+".",
                    "A",
                    re.sub("/[0-9]*", "", str(nb_vm.primary_ip4)),
                    forward_zone_canonical
                ))
            if nb_vm.primary_ip6:
                host_ips.append((
                    nb_vm.name+".",
                    "AAAA",
                    re.sub("/[0-9]*", "", str(nb_vm.primary_ip6)),
                    forward_zone_canonical
                ))

    # get zone forward_zone_canonical form PowerDNS
    zone = pdns.get_zone(forward_zone_canonical)

    # assemble list with tupels containing the canonical name, the record type,
    # the IP address and forward_zone_canonical without the subnet from
    # PowerDNS zone records with the
    # comment "NetBox"
    if zone:
        for record in zone.records:
            for comment in record["comments"]:
                if comment["content"] == "NetBox": 
                    for ip in record["records"]:
                        record_ips.append((record["name"],
                                           record["type"],
                                           ip["content"],
                                           forward_zone_canonical))

for reverse_zone in REVERSE_ZONES:
    if reverse_zone["zone"].endswith("."):
        reverse_zone_canonical = reverse_zone["zone"]+"."
    else:
        reverse_zone_canonical = reverse_zone["zone"]

    # get IPs within the prefix from NetBox
    nb_ips = nb.ipam.ip_addresses.filter(parent=reverse_zone["prefix"])

    # assemble list with tupels containing the canonical name, the record type
    # and the IP address without the subnet from NetBox IPs
    for nb_ip in nb_ips:
        if nb_ip.dns_name != "":
            ip = re.sub("/[0-9]*", "", str(nb_ip))
            reverse_pointer = ipaddress.ip_address(ip).reverse_pointer
            host_ips.append((reverse_pointer+".",
                             "PTR",
                             nb_ip.dns_name+".",
                             reverse_zone_canonical))

    # get zone forward_zone_canonical form PowerDNS
    zone = pdns.get_zone(reverse_zone_canonical)

    # assemble list with tupels containing the canonical name, the record type,
    # the IP address and forward_zone_canonical without the subnet from
    # PowerDNS zone records with the
    # comment "NetBox"
    for record in zone.records:
        for comment in record["comments"]:
            if comment["content"] == "NetBox":
                for ip in record["records"]:
                    record_ips.append((record["name"],
                                       record["type"],
                                       ip["content"],
                                       reverse_zone_canonical))

# create set with tupels that have to be created
# tupels from NetBox without tupels that already exists in PowerDNS
to_create = set(host_ips)-set(record_ips)

# create set with tupels that have to be deleted
# tupels from PowerDNS without tupels that are documented in NetBox
to_delete = set(record_ips)-set(host_ips)

print("----")

print(len(to_create), "records to create:")
for record in to_create:
    print(record[0])

print("----")

print(len(to_delete), "records to delete:")
for record in to_delete:
    print(record[0])

print("----")

if DRY_RUN:
    print("Skipping Create/Delete due to Dry Run")
    print("----")
    sys.exit()

for record in to_create:
    print("Creating", record)
    zone = pdns.get_zone(record[3])
    zone.create_records([
                        powerdns.RRSet(
                            record[0],
                            record[1],
                            [(record[2], False)],
                            comments=[powerdns.Comment("NetBox")])
                        ])

print("----")

for record in to_delete:
    print("Deleting", record)
    zone = pdns.get_zone(record[3])
    zone.delete_records([
                        powerdns.RRSet(
                            record[0],
                            record[1],
                            [(record[2], False)],
                            comments=[powerdns.Comment("NetBox")])
                        ])
    
print("----")
