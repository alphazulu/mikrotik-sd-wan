# LAB ONLY: generated baseline for a clean CHR. Password is set separately.
/system identity set name=sdwan-client
/ip dhcp-client remove [find]
/ip address add address=10.77.10.15/24 interface=ether1 comment=lab-management
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
/ip address add address=192.168.50.101/24 interface=ether2
/ip address add address=192.168.50.102/24 interface=ether2
/ip route add dst-address=0.0.0.0/0 gateway=192.168.50.1
/ip dns set servers=192.168.50.1 allow-remote-requests=no
/ip firewall filter add chain=forward action=drop
