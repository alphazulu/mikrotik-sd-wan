"""Small AT subset for the optional CDC ACM management interface.

Unknown commands return ERROR immediately so RouterOS does not wait out a timeout.
The responses come from LteState. They do not configure the uplink.
"""

from __future__ import annotations

_ACT = {"GSM": 0, "UMTS": 2, "LTE": 7, "NR": 12}
_REG = {
    "registered": 1,
    "searching": 2,
    "denied": 3,
    "unknown": 4,
    "roaming": 5,
}


def csq_from_rssi(rssi: int) -> int:
    value = int(round((rssi + 113) / 2))
    if value < 0:
        return 0
    if value > 31:
        return 31
    return value


class AtPort:
    def __init__(self, state_provider):
        self._state = state_provider
        self.echo = True
        self._buf = b""

    def reset(self) -> None:
        self.echo = True
        self._buf = b""

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data.replace(b"\x00", b"")
        replies: list[bytes] = []
        while b"\r" in self._buf or b"\n" in self._buf:
            cut = len(self._buf)
            for index, byte in enumerate(self._buf):
                if byte in (13, 10):
                    cut = index
                    break
            line = self._buf[:cut].decode("ascii", "replace")
            rest = self._buf[cut:]
            while rest[:1] in (b"\r", b"\n"):
                rest = rest[1:]
            self._buf = rest
            if not line.strip():
                continue
            replies.append(self._format(line.strip()))
        return replies

    def _format(self, line: str) -> bytes:
        body, ok = self._dispatch(line)
        echo = (line + "\r").encode("ascii", "replace") if self.echo else b""
        if body and body.startswith("+CME ERROR"):
            return echo + b"\r\n" + body.encode("ascii", "replace") + b"\r\n"
        if body:
            return echo + b"\r\n" + body.encode("ascii", "replace") + b"\r\nOK\r\n"
        if ok:
            return echo + b"\r\nOK\r\n"
        return echo + b"\r\nERROR\r\n"

    def _dispatch(self, line: str) -> tuple[str | None, bool]:
        cmd = line.upper()
        if cmd == "ATE0":
            self.echo = False
            return None, True
        if cmd in ("ATE1", "ATE"):
            self.echo = True
            return None, True
        radio = self._state()
        if cmd == "AT":
            return None, True
        if cmd == "ATI":
            return "\r\n".join((radio["manufacturer"], radio["model"], radio["revision"])), True
        if cmd == "AT+CGMI":
            return radio["manufacturer"], True
        if cmd == "AT+CGMM":
            return radio["model"], True
        if cmd == "AT+CGMR":
            return radio["revision"], True
        if cmd in ("AT+CGSN", "AT+GSN"):
            return radio["imei"], True
        if cmd == "AT+CIMI":
            return radio["imsi"], True
        if cmd in ("AT+CCID", "AT+ICCID"):
            return radio["iccid"], True
        if cmd == "AT+CPIN?":
            pin = radio["pin_status"]
            if pin == "ready":
                return "+CPIN: READY", True
            if pin == "sim-pin":
                return "+CPIN: SIM PIN", True
            return "+CME ERROR: 10", False
        if cmd in ("AT+CSQ", "AT+CSQ?"):
            if radio["registration_status"] not in ("registered", "roaming"):
                return "+CSQ: 99,99", True
            return f"+CSQ: {csq_from_rssi(int(radio['rssi']))},99", True
        if cmd in ("AT+CREG?", "AT+CGREG?", "AT+CEREG?"):
            name = cmd.split("+", 1)[1].split("?", 1)[0]
            stat = _REG[radio["registration_status"]]
            return f"+{name}: 0,{stat}", True
        if cmd == "AT+COPS?":
            if radio["registration_status"] not in ("registered", "roaming"):
                return "+COPS: 0", True
            act = _ACT[radio["access_technology"]]
            return f'+COPS: 0,0,"{radio["operator"]}",{act}', True
        if cmd == "AT+CGDCONT?":
            # Display only. The emulator does not open a PDP context.
            return f'+CGDCONT: 1,"IP","{radio["apn"]}","0.0.0.0",0,0', True
        return None, False
