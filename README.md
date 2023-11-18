# netbox-powerdns-sync

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**netbox-powerdns-sync** is an open-source project that provides a Python script which puts DNS entries from NetBox into PowerDNS. 

## Installation

Download this repository and nstall the dependencies:

```bash
pip install -r requirements.txt
```

## PowerDNS preperation

Make sure all zones (forward and reverse) already exist in PowerDNS.

## Configuration

Create a `config.py` file like this:

```python
# URL of your NetBox installation
NB_URL = "https://netbox.local/"
# NetBox API token (read-only is sufficent)
NB_TOKEN = ""

# URL of your PowerDNS API endpoint
PDNS_API_URL = "http://powerdns.local:8081/api/v1"
# PowerDNS API key
PDNS_KEY = ""

# Forward Zones that should be matched in NetBox for import into PowerDNS
FORWARD_ZONES = ["local"]
# Prefixes that from NetBox with corresponding .arpa Zones for import into PowerDNS
REVERSE_ZONES = [{"zone": "10.10.10.in-addr.arpa.", "prefix": "10.10.10/24"}]

# Only create reverse pointers for NetBox IP objects that have a matching custom field value
PTR_ONLY_CF = False

# Only output changes to CLI, do not change PowerDNS
DRY_RUN = True

# Use IP dns_name as source for sync
SOURCE_IP = True
# Use device name as source for sync
SOURCE_DEVICE = True
# Use VM name as source for sync
SOURCE_VM = True
```

## Execution

```bash
python netbox-powerdns-sync.py
```

## Contribution

We welcome contributions and suggestions! If you find a bug or want to add a feature, please create an issue or a pull request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
