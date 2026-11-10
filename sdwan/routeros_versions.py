"""Explicit opt-in for a bounded, unqualified hardware laboratory candidate.

The published validated target remains 7.24.5. Do not infer compatibility from
major/minor numbers or silently allow every version present on a device.
"""
import os

BASE_VERSION='7.24.5'
LAB_VERSIONS=frozenset({'7.25.1'})

def allowed(version):
    return version==BASE_VERSION or (version in LAB_VERSIONS and os.environ.get('SDWAN_EXPERIMENTAL_ROUTEROS')==version)

def require(resource):
    version=resource.get('version','').split()[0] if resource.get('version') else ''
    if not allowed(version):
        raise ValueError('Validated RouterOS target is '+BASE_VERSION+'; this version requires a supported explicit laboratory opt-in: '+(version or 'unknown'))
    return version
