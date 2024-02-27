#!/usr/bin/env python3

import argparse
import ipaddress
import logging
import re
import sys

from collections import Counter
from systemd.journal import JournalHandler

import powerdns
import pynetbox

from config import NB_URL, NB_TOKEN, PDNS_API_URL, PDNS_KEY
from config import FORWARD_ZONES, REVERSE_ZONES, DRY_RUN
from config import SOURCE_DEVICE, SOURCE_IP, SOURCE_VM
from config import PTR_ONLY_CF


def make_canonical(zone):
    # return a zone in canonical form
    return zone+"."


def get_host_ips_ip(nb, zone):
    # return list of tupels for ip addresses
    host_ips = []

    # get IPs with DNS name ending in forward_zone from NetBox
    if PTR_ONLY_CF:
        nb_ips = nb.ipam.ip_addresses.filter(dns_name__iew=zone,
                                             status=["active",
                                                     "dhcp",
                                                     "slaac"],
                                             cf_ptr_only=False)
    else:
        nb_ips = nb.ipam.ip_addresses.filter(dns_name__iew=zone,
                                             status=["active",
                                                     "dhcp",
                                                     "slaac"])
    
    # assemble list with tupels containing the canonical name, the record
    # type and the IP address without the subnet from NetBox IPs
    for nb_ip in nb_ips:
        nb_zone = nb_ip.dns_name.split(".")
        if zone != ".".join(nb_zone[1:]):
            continue
        if nb_ip.family.value == 6:
            type = "AAAA"
        else:
            type = "A"
        host_ips.append((
            make_canonical(nb_ip.dns_name),
            type,
            re.sub("/[0-9]*", "", str(nb_ip)),
            make_canonical(zone)
        ))

    return host_ips


def get_host_ips_ip_reverse(nb, prefix, zone):
    # return list of reverse zone tupels for ip addresses
    host_ips = []

    # get IPs within the prefix from NetBox
    nb_ips = nb.ipam.ip_addresses.filter(parent=prefix,
                                         status=["active",
                                                 "dhcp",
                                                 "slaac"])
    
    # assemble list with tupels containing the canonical name, the record type
    # and the IP address without the subnet from NetBox IPs
    for nb_ip in nb_ips:
        if nb_ip.dns_name != "":
            ip = re.sub("/[0-9]*", "", str(nb_ip))
            reverse_pointer = ipaddress.ip_address(ip).reverse_pointer
            host_ips.append((make_canonical(reverse_pointer),
                             "PTR",
                             make_canonical(nb_ip.dns_name),
                             make_canonical(zone)))

    return host_ips


def get_host_ips_device(nb, zone):
    # return list of tupels for devices
    # get devices with name ending in forward_zone from NetBox
    nb_devices = nb.dcim.devices.filter(name__iew=zone,
                                        status=["active",
                                                "failed",
                                                "offline",
                                                "staged"])

    return get_host_ips_host(nb_devices, zone)


def get_host_ips_vm(nb, zone):
    # return list of tupels for VMs
    # get VMs with name ending in forward_zone from NetBox
    nb_vms = nb.virtualization.virtual_machines.filter(
        name__iew=zone,
        status=["active",
                "failed",
                "offline",
                "staged"])

    return get_host_ips_host(nb_vms, zone)


def get_host_ips_host(nb_hosts, zone):
    # return list of tupels for hosts (NetBox devices/VMs)
    host_ips = []

    # assemble list with tupels containing the canonical name, the record
    # type and the IP addresses without the subnet of the device/vm
    for nb_host in nb_hosts:
        if nb_host.primary_ip4:
            host_ips.append((
                make_canonical(nb_host.name),
                "A",
                re.sub("/[0-9]*", "", str(nb_host.primary_ip4)),
                make_canonical(zone)
            ))
        if nb_host.primary_ip6:
            host_ips.append((
                make_canonical(nb_host.name),
                "AAAA",
                re.sub("/[0-9]*", "", str(nb_host.primary_ip6)),
                make_canonical(zone)
            ))


def main():
    parser = argparse.ArgumentParser(
        description="Sync DNS name entries from NetBox to PowerDNS",
        epilog="""This script uses the REST API of NetBox to retriev
        IP addresses and their DNS name. It then syncs the DNS names
        to PowerDNS to create A, AAAA and PTR records.
        It does this for forward and reverse zones specified in the config
        file.
        """)
    parser.add_argument("--dry_run", "-d", action='store_true',
                        help="Perform a dry run (make no changes to PowerDNS)")
    parser.add_argument("--loglevel", "-l", type=str, default="INFO",
                        choices=["WARNING", "INFO", ""],
                        help="Log level for the console logger")
    parser.add_argument("--loglevel_journal", "-j", type=str, default="",
                        choices=["WARNING", "INFO", ""],
                        help="Log level for the systemd journal logger")
    args = parser.parse_args()

    # merge dry_run directives from config and arguments
    dry_run = False
    if args.dry_run or DRY_RUN:
        dry_run = True

    logger = logging.getLogger(__name__)
    # set overall log level to debug to catch all
    logger.setLevel(logging.DEBUG)
    # loglevel for console logging
    if args.loglevel != "":
        handler = logging.StreamHandler()
        handler.setLevel(getattr(logging, args.loglevel))
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    # loglevel for journal logging
    if args.loglevel_journal != "":
        journal_handler = JournalHandler()
        journal_handler.setLevel(getattr(logging, args.loglevel_journal))
        logger.addHandler(journal_handler)

    nb = pynetbox.api(NB_URL, token=NB_TOKEN)
    
    pdns_api_client = powerdns.PDNSApiClient(api_endpoint=PDNS_API_URL,
                                             api_key=PDNS_KEY)
    pdns = powerdns.PDNSEndpoint(pdns_api_client).servers[0]
    
    host_ips = []
    record_ips = []
    for forward_zone in FORWARD_ZONES:    
        # Source IP: Create domains based on DNS name attached to IPs
        if SOURCE_IP:
            host_ips += get_host_ips_ip(nb, forward_zone)
        # Source device: Create domains based on the name of devices
        if SOURCE_DEVICE:
            host_ips += get_host_ips_device(nb, forward_zone)
        # Source VM: Create domains based on the name of VMs
        if SOURCE_VM:
            host_ips += get_host_ips_vm(nb, forward_zone)
    
        # get zone forward_zone_canonical form PowerDNS
        zone = pdns.get_zone(make_canonical(forward_zone))
    
        # assemble list with tupels containing the canonical name, the record
        # type, the IP address and forward_zone_canonical without the subnet
        # from PowerDNS zone records with the
        # comment "NetBox"
        if zone:
            for record in zone.records:
                for comment in record["comments"]:
                    if comment["content"] == "NetBox": 
                        for ip in record["records"]:
                            record_ips.append((record["name"],
                                               record["type"],
                                               ip["content"],
                                               make_canonical(forward_zone)))
    
    for reverse_zone in REVERSE_ZONES:
        host_ips += get_host_ips_ip_reverse(nb, reverse_zone["prefix"],
                                            reverse_zone["zone"])

        # get reverse zone records form PowerDNS
        zone = pdns.get_zone(make_canonical(reverse_zone["zone"]))
    
        # assemble list with tupels containing the canonical name, the record
        # type, the IP address and forward_zone_canonical without the subnet
        # from PowerDNS zone records with the
        # comment "NetBox"
        for record in zone.records:
            for comment in record["comments"]:
                if comment["content"] == "NetBox":
                    for ip in record["records"]:
                        record_ips.append((record["name"],
                                           record["type"],
                                           ip["content"],
                                           make_canonical(reverse_zone["zone"])))
    
    # find duplicates in host_ips
    duplicate_records = [(host_ip[0], host_ip[1]) for host_ip in host_ips]
    duplicate_records = [duplicate for duplicate, amount in
                         Counter(duplicate_records).items() if amount > 1]
    for duplicate_record in duplicate_records:
        logger.critical(f"""Detected duplicate record from NetBox \
{duplicate_record[0]} of type {duplicate_record[1]}.
Not continuing execution. Please resolve the duplicate.""")
    if len(duplicate_records) > 0:
        sys.exit()

    # create set with tupels that have to be created
    # tupels from NetBox without tupels that already exists in PowerDNS
    to_create = set(host_ips)-set(record_ips)
    
    # create set with tupels that have to be deleted
    # tupels from PowerDNS without tupels that are documented in NetBox
    to_delete = set(record_ips)-set(host_ips)
        
    logger.info(f"{len(to_create)} records to create")
    for record in to_create:
        logger.info(f"Will create record {record[0]}")
        
    logger.info(f"{len(to_delete)} records to delete")
    for record in to_delete:
        logger.info(f"Will delete record {record[0]}")
        
    if dry_run:
        logger.info("Skipping Create/Delete due to Dry Run")
        sys.exit()
    
    for record in to_create:
        logger.info(f"Now creating {record}")
        zone = pdns.get_zone(record[3])
        zone.create_records([
                            powerdns.RRSet(
                                record[0],
                                record[1],
                                [(record[2], False)],
                                comments=[powerdns.Comment("NetBox")])
                            ])
        
    for record in to_delete:
        logger.info(f"Now deleting {record}")
        zone = pdns.get_zone(record[3])
        zone.delete_records([
                            powerdns.RRSet(
                                record[0],
                                record[1],
                                [(record[2], False)],
                                comments=[powerdns.Comment("NetBox")])
                            ])


if __name__ == "__main__":
    main()
