# LAB ONLY: generated baseline for a clean CHR. Password is set separately.
/system identity set name=sdwan-isp1
/ip dhcp-client remove [find]
/ip address add address=10.77.1.15/24 interface=ether1 comment=lab-management
/ip service disable [find where dynamic=no]
/ip service set [find where name=www and dynamic=no] disabled=no
/ip service set [find where name=ssh and dynamic=no] disabled=no
/ip service set [find where name=winbox and dynamic=no] disabled=no
/ip service set [find where name=api and dynamic=no] disabled=no
/tool mac-server set allowed-interface-list=none
/tool mac-server mac-winbox set allowed-interface-list=none
/ip neighbor discovery-settings set discover-interface-list=none
/ip firewall filter add chain=input connection-state=established,related action=accept
/ip firewall filter add chain=input connection-state=invalid action=drop
/ip firewall filter add chain=input in-interface=ether1 action=accept comment=lab-management
/ip firewall filter add chain=input protocol=icmp action=accept
/ip firewall filter add chain=input action=drop
/ip firewall filter add chain=forward connection-state=established,related action=accept
/ip firewall filter add chain=forward connection-state=invalid action=drop
/ip route add dst-address=0.0.0.0/0 gateway=10.77.1.2
/ip address add address=172.20.1.1/30 interface=ether2
/ip address add address=198.18.1.1/32 interface=lo comment=deterministic-probe
/ip address add address=198.19.0.1/32 interface=lo comment=shared-probe
/ip firewall filter add chain=input dst-address=198.19.0.1 protocol=icmp action=accept comment=path-proof place-before=0
/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade
/ip firewall filter add chain=forward in-interface=ether2 out-interface=ether1 action=accept
/ip dns set servers=10.77.1.3 allow-remote-requests=yes
/ip firewall filter add chain=input in-interface=ether2 protocol=udp dst-port=53 action=accept comment=lab-dns place-before=0
/ip firewall filter add chain=input in-interface=ether2 protocol=tcp dst-port=53 action=accept comment=lab-dns place-before=0
/ip firewall filter add chain=forward action=drop
