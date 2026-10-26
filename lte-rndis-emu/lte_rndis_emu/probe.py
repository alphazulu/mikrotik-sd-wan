"""Prove which USB path this kernel can actually run. Do not modprobe blindly."""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess


def _read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def _config_text() -> str | None:
    if os.path.exists("/proc/config.gz"):
        try:
            with gzip.open("/proc/config.gz", "rt", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return None
    for path in sorted(os.listdir("/boot")) if os.path.isdir("/boot") else []:
        if path.startswith("config-"):
            return _read_text(os.path.join("/boot", path))
    return None


def _flag(config: str | None, name: str) -> bool | None:
    if config is None:
        return None
    enabled = f"{name}=y"
    disabled = f"# {name} is not set"
    for line in config.splitlines():
        if line.strip() == enabled or line.startswith(name + "="):
            return True
        if line.strip() == disabled:
            return False
    return None


def _which(name: str) -> str | None:
    return shutil.which(name)


def _help(binary: str) -> str | None:
    try:
        result = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or "") + (result.stderr or "")
    return text[:4000]


def collect() -> dict:
    config = _config_text()
    udc = []
    if os.path.isdir("/sys/class/udc"):
        udc = sorted(os.listdir("/sys/class/udc"))
    usb_bus = os.path.isdir("/dev/bus/usb")
    modules = _read_text("/proc/modules") or ""
    uname = _read_text("/proc/version") or os.uname().version
    qemu = _which("qemu-system-x86_64")
    usbredir = _which("usbredirserver")
    return {
        "uname": uname.strip(),
        "config_usb_support": _flag(config, "CONFIG_USB_SUPPORT"),
        "config_usb_gadget": _flag(config, "CONFIG_USB_GADGET"),
        "config_usb_libcomposite": _flag(config, "CONFIG_USB_LIBCOMPOSITE"),
        "config_usb_configfs": _flag(config, "CONFIG_USB_CONFIGFS"),
        "config_usb_configfs_rndis": _flag(config, "CONFIG_USB_CONFIGFS_RNDIS"),
        "config_usb_dummy_hcd": _flag(config, "CONFIG_USB_DUMMY_HCD"),
        "config_usbip": _flag(config, "CONFIG_USBIP_CORE"),
        "config_present": config is not None,
        "udc": udc,
        "usb_bus": usb_bus,
        "loaded_modules_matching_usb": [line.split()[0] for line in modules.splitlines() if "usb" in line.lower()],
        "qemu_system_x86_64": qemu,
        "lsusb": _which("lsusb"),
        "usbredirserver": usbredir,
        "usbredirserver_help": _help(usbredir) if usbredir else None,
        "usbip": _which("usbip"),
        "modprobe_attempted": False,
        "kernel_rebuild_attempted": False,
    }


def decide(evidence: dict) -> dict:
    usb = evidence.get("config_usb_support")
    gadget = evidence.get("config_usb_gadget")
    dummy = evidence.get("config_usb_dummy_hcd")
    configfs_rndis = evidence.get("config_usb_configfs_rndis")
    udc = evidence.get("udc") or []
    rejected = []
    if usb is False:
        rejected.extend(["configfs-dummy-hcd", "usb-host", "usbip", "usbredirserver-on-local-gadget"])
        return {
            "path": "usbredir-userspace",
            "reason": (
                "CONFIG_USB_SUPPORT is not set. There is no host controller, no UDC, "
                "and no place to load dummy_hcd, libcomposite or f_rndis. "
                "modprobe and a rebuild of this kernel are not attempted. "
                "QEMU must attach the userspace RNDIS device with -device usb-redir. "
                "A separate Linux VM with USB gadget support is only needed if a real "
                "lsusb entry on a gadget host is mandatory; this process does not provide one."
            ),
            "rejected": rejected,
            "lsusb": "impossible on this kernel",
            "comparable_enumeration": "python3 -m lte_rndis_emu enumerate",
        }
    if udc and (configfs_rndis is not False) and gadget is not False:
        return {
            "path": "configfs-dummy-hcd",
            "reason": (
                "A UDC is already present and gadget config does not forbid f_rndis. "
                "Use scripts/gadget-configfs.sh, confirm the gadget with lsusb, then "
                "try qemu -device usb-host. If libusb cannot claim it, export that "
                "same device with usbredirserver on 127.0.0.1 and use -device usb-redir. "
                "Do not mix usbip with usbredir."
            ),
            "rejected": ["usbip-unless-imported-then-usb-host"],
            "lsusb": "required before claiming usb-host works",
            "comparable_enumeration": "lsusb -v",
        }
    if usb is True and dummy is False and not udc:
        rejected.append("in-kernel-dummy-hcd")
        return {
            "path": "usbredir-userspace",
            "reason": (
                "USB is built in but CONFIG_USB_DUMMY_HCD is off and /sys/class/udc is empty. "
                "Do not rebuild this kernel here. Use the userspace usbredir device, or boot "
                "a different Linux VM whose kernel has dummy_hcd and f_rndis, then bridge "
                "that gadget to QEMU with usbredir. Leave the existing CHR launch path otherwise unchanged."
            ),
            "rejected": rejected,
            "lsusb": "no gadget to enumerate",
            "comparable_enumeration": "python3 -m lte_rndis_emu enumerate",
        }
    if usb is None and not udc:
        return {
            "path": "unproven",
            "reason": (
                "Kernel config and /sys/class/udc do not prove gadget support. "
                "Do not modprobe. Run this probe on the lab host. Until a UDC exists, "
                "use the userspace usbredir device rather than assuming usb-host works."
            ),
            "rejected": ["assumed-usb-host"],
            "lsusb": "not proven",
            "comparable_enumeration": "python3 -m lte_rndis_emu enumerate",
        }
    return {
        "path": "usbredir-userspace",
        "reason": "No usable UDC was found. Userspace usbredir is the path that does not need one.",
        "rejected": ["usb-host-without-a-device"],
        "lsusb": "no device",
        "comparable_enumeration": "python3 -m lte_rndis_emu enumerate",
    }


def report() -> dict:
    evidence = collect()
    decision = decide(evidence)
    return {"decision": decision, "evidence": evidence}
