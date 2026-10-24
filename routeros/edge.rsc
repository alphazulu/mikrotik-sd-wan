# LAB ONLY: generated baseline for a clean CHR. Password is set separately.
/system identity set name=sdwan-edge
/ip dhcp-client remove [find]
/ip address add address=10.77.0.15/24 interface=ether1 comment=lab-management
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
/interface list add name=WAN
/ip address add address=192.168.50.1/24 interface=ether5
/routing table add name=prefer-wan2 fib
/ip address add address=172.20.1.2/30 interface=ether2
/interface list member add list=WAN interface=ether2
/ip route add dst-address=198.18.1.1/32 gateway=172.20.1.1 comment=probe-wan1
/ip route add dst-address=0.0.0.0/0 gateway=172.20.1.1 distance=1 check-gateway=ping comment=baseline-wan1
/routing table add name=probe-wan1 fib
/ip route add dst-address=0.0.0.0/0 gateway=172.20.1.1@main routing-table=probe-wan1 comment=pinned-wan1
/ip route add dst-address=0.0.0.0/0 gateway=172.20.1.1@main routing-table=prefer-wan2 distance=2 check-gateway=ping comment=client102-wan1
/ip address add address=172.20.2.2/30 interface=ether3
/interface list member add list=WAN interface=ether3
/ip route add dst-address=198.18.2.1/32 gateway=172.20.2.1 comment=probe-wan2
/ip route add dst-address=0.0.0.0/0 gateway=172.20.2.1 distance=2 check-gateway=ping comment=baseline-wan2
/routing table add name=probe-wan2 fib
/ip route add dst-address=0.0.0.0/0 gateway=172.20.2.1@main routing-table=probe-wan2 comment=pinned-wan2
/ip route add dst-address=0.0.0.0/0 gateway=172.20.2.1@main routing-table=prefer-wan2 distance=1 check-gateway=ping comment=client102-wan2
/ip address add address=172.20.3.2/30 interface=ether4
/interface list member add list=WAN interface=ether4
/ip route add dst-address=198.18.3.1/32 gateway=172.20.3.1 comment=probe-wan3
/ip route add dst-address=0.0.0.0/0 gateway=172.20.3.1 distance=3 check-gateway=ping comment=baseline-wan3
/routing table add name=probe-wan3 fib
/ip route add dst-address=0.0.0.0/0 gateway=172.20.3.1@main routing-table=probe-wan3 comment=pinned-wan3
/ip route add dst-address=0.0.0.0/0 gateway=172.20.3.1@main routing-table=prefer-wan2 distance=3 check-gateway=ping comment=client102-wan3
/routing rule add src-address=192.168.50.102/32 action=lookup-only-in-table table=prefer-wan2
/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade
/ip firewall filter add chain=forward in-interface=ether5 out-interface-list=WAN action=accept
/ip dns set servers=172.20.1.1,172.20.2.1,172.20.3.1 allow-remote-requests=yes
/ip firewall filter add chain=input in-interface=ether5 protocol=udp dst-port=53 action=accept comment=lab-dns place-before=0
/ip firewall filter add chain=input in-interface=ether5 protocol=tcp dst-port=53 action=accept comment=lab-dns place-before=0
/ip firewall filter add chain=forward action=drop
