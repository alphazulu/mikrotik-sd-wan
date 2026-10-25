"""Experimental derived controller. Not selected by the SDK until acceptance."""
from pathlib import Path

def controller_source(root: Path, config=None) -> str:
    root=Path(root)
    source=(root/'native/sdwan-controller.rsc').read_text()
    helper=(root/'container-controller/routeros/bridge.rsc').read_text()
    if config is not None:
        from .container_config import addresses
        _,_,container_ip=addresses(config)
        helper=helper.replace('"172.31.255.2"','"'+container_ip+'"')
    def replace_once(old: str, new: str) -> None:
        nonlocal source
        if source.count(old)!=1:
            raise ValueError('Native controller changed; review container adapter anchor: '+old[:70])
        source=source.replace(old,new,1)
    anchor='    :foreach policy in=($cfg->"policies") do={\n'
    replace_once(anchor,'''    :local containerBridge [:toarray ""]
    :set ($containerBridge->"active") false
    :onerror bridgeError in={
        :set containerBridge [$sdwanContainerBridge cfg=$cfg raw=$raw now=$now dir=$dir]
    } do={
        # A failing optional adapter must not interrupt native SLA/failover.
        :set ($containerBridge->"error") "container adapter unavailable"
    }
'''+anchor)
    replace_once('        :local decision [:toarray ""]\n','''        # Revalidate cached intent against CURRENT native SLA, including fresh
        # generation barriers. A stale selected WAN cannot bypass eligibility.
        :local containerDecision false
        :if ($containerBridge->"active") do={
            :local wanted (($containerBridge->"selected")->$pn)
            :local eligible ($wanted = "none")
            :if ($wanted != "none") do={
                :local state ($sdwanState->(($policy->"profile") . "/" . $wanted))
                :if (((($maintenance->$wanted)->"admit") = true) && (($state = "healthy") || (($state = "degraded") && ($policy->"allow_degraded")))) do={ :set eligible true }
            }
            :if ($eligible) do={ :set selected $wanted; :set containerDecision true }
        }
        :local decision [:toarray ""]
''')
    anchor='        :set ($decision->"selected") $selected; :set ($decision->"reason") $why\n'
    replace_once(anchor,'''        :if ($containerDecision) do={ :set why "local Rust container intent; current RouterOS SLA validated" }
'''+anchor)
    replace_once('    :set ($output->"controller") "RouterOS local script + scheduler"\n','''    :set ($output->"container") $containerBridge
    :set ($output->"backend") "container"
    :set ($output->"controller") "RouterOS local container adapter; native fallback"
''')
    replace_once(':onerror err in={\n',helper+'\n:onerror err in={\n')
    source=source.replace(':return }',':return "" }').replace(':return\n',':return ""\n')
    if len(source.encode())>=64000:
        raise ValueError('Derived controller exceeds conservative RouterOS script limit')
    return source

def installer_source(root: Path,config) -> str:
    from .container_config import NAME,VETH
    source=(Path(root)/'native/sdwan-install.rsc').read_text()
    anchor=':if (($cfg->"schema_version") != 1) do={ :error "unsupported SDWAN schema" }\n'
    if source.count(anchor)!=1:raise ValueError('Native installer changed; review container guard anchor')
    guard=f''':local containerID [/container/find where name="{NAME}" and comment="sdwan-container:controller"]
:if ([:len $containerID] != 1) do={{ :error "prepare the local SDWAN container first" }}
:if ([/container/get $containerID interface] != "{VETH}") do={{ :error "prepared container interface changed" }}
'''
    source=source.replace(anchor,anchor+guard,1)
    source+=f'''
# Start the local decision process inside the protected worker transaction.
# Watchdog readiness additionally requires its accepted live lease.
/container/set $containerID start-on-boot=yes
:if ([:len [/container/find where name="{NAME}" and running=yes]] = 0) do={{ /container/start $containerID }}
'''
    return source

def watchdog_source(root: Path) -> str:
    source=(Path(root)/'native/sdwan-deploy-watchdog.rsc').read_text()
    anchor='                :set ready true\n'
    if source.count(anchor)!=1:raise ValueError('Native watchdog changed; review container readiness anchor')
    source=source.replace(anchor,'''                :set ready true
                :if (([:typeof (($status->"container")->"active")] != "bool") || ((($status->"container")->"active") != true)) do={ :set ready false }
''',1)
    return source.replace(':return }',':return "" }').replace(':return\n',':return ""\n')
