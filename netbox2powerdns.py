import powerdns
import pynetbox
import re

from config import NB_URL, NB_TOKEN, PDNS_API_URL, PDNS_KEY

nb = pynetbox.api(NB_URL, token=NB_TOKEN)

pdns_api_client = powerdns.PDNSApiClient(api_endpoint=PDNS_API_URL, api_key=PDNS_KEY)
pdns = powerdns.PDNSEndpoint(pdns_api_client).servers[0]

# get IPs with DNS name ending in "intern.relaix.net" from NetBox
nb_ips = nb.ipam.ip_addresses.filter(dns_name__iew="intern.relaix.net")

# assemble list with tupels containing the canonical name, the record type and
# and the IP address without the subnet from NetBox IPs
host_ips = []
for nb_ip in nb_ips:
    if nb_ip.family.value == 6:
        type = "AAAA"
    else:
        type = "A"
    host_ips.append((nb_ip.dns_name+".", type, re.sub("/[0-9]*", "", str(nb_ip))))

# get zone "intern.relaix.net." form PowerDNS
zone = pdns.get_zone("intern.relaix.net.")

# assemble list with tupels containing the canonical name, the record type and
# and the IP address without the subnet from PowerDNS zone records with the
# comment "NetBox"
record_ips = []
for record in zone.records:
    for comment in record["comments"]:
        if comment["content"] == "NetBox":
            for ip in record["records"]:
                record_ips.append((record["name"], record["type"], ip["content"]))

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

for record in to_create:
    print("Creating", record)
    zone.create_records([powerdns.RRSet(record[0], record[1], [(record[2], False)], comments=[powerdns.Comment("NetBox")])])

print("----")

for record in to_delete:
    print("Deleting", record)
    zone.create_records([powerdns.RRSet(record[0], record[1], [(record[2], False)], comments=[powerdns.Comment("NetBox")])])

print("----")
