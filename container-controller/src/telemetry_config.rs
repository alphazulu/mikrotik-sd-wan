//! Mounted public settings only. Runtime web code is a separate Cargo feature.
use serde::Deserialize;
use std::net::{Ipv4Addr,SocketAddr};
use std::path::PathBuf;

#[derive(Clone,Deserialize)]
#[serde(default,deny_unknown_fields)]
pub struct Settings {
    pub enabled:bool,
    pub listen:SocketAddr,
    pub token_file:PathBuf,
    pub allowed_sources:Vec<String>,
    pub sample_seconds:u64,
    pub history_points:usize,
    pub profile:String,
}
impl Default for Settings {
    fn default()->Self {Self{enabled:false,listen:"172.31.255.2:8080".parse().unwrap(),token_file:"/secrets/web-token".into(),allowed_sources:vec![],sample_seconds:10,history_points:360,profile:"default".into()}}
}
#[derive(Clone,Copy)]
pub struct Network {address:u32,mask:u32}
impl Network {
    pub fn parse(value:&str)->Result<Self,&'static str> {
        let (address,prefix)=value.split_once('/').ok_or("Web sources require explicit IPv4 prefixes")?;
        let ip:Ipv4Addr=address.parse().map_err(|_|"Invalid IPv4 web source")?;
        let prefix:u32=prefix.parse().map_err(|_|"Invalid IPv4 web prefix")?;
        if prefix==0 || prefix>32 {return Err("Unsafe IPv4 web prefix");}
        let mask=u32::MAX<<(32-prefix);let address=u32::from(ip);
        if address & !mask !=0 {return Err("Web source must be a canonical IPv4 network");}
        let end=Ipv4Addr::from(address|!mask);
        if !(ip.is_private()&&end.is_private() || ip.is_loopback()&&end.is_loopback()) {return Err("Web sources must stay in private or loopback ranges");}
        // A broad prefix cannot cross between separate RFC1918 ranges.
        let ranges=[(0x0a000000,8),(0xac100000,12),(0xc0a80000,16),(0x7f000000,8)];
        if !ranges.iter().any(|(base,bits)|prefix>=*bits && address & (u32::MAX<<(32-bits))==*base) {return Err("Web source crosses a private range boundary");}
        Ok(Self{address,mask})
    }
    pub fn contains(&self,ip:Ipv4Addr)->bool {u32::from(ip)&self.mask==self.address}
}
impl Settings {
    pub fn validate(&self)->Result<Vec<Network>,&'static str> {
        if !self.enabled {return Ok(vec![]);}
        if !(5..=60).contains(&self.sample_seconds) || !(12..=600).contains(&self.history_points) {return Err("Web sampling/history bounds exceeded");}
        if self.listen.port()<1024 || !self.listen.ip().is_ipv4() {return Err("Web requires a private IPv4 high port");}
        let std::net::IpAddr::V4(ip)=self.listen.ip() else {return Err("IPv4 web listener required")};
        if !(ip.is_private() || ip.is_loopback()) {return Err("Web listener must be private or loopback");}
        if self.token_file!=std::path::Path::new("/secrets/web-token") {return Err("Dedicated web token mount required");}
        if self.allowed_sources.is_empty() || self.allowed_sources.len()>16 {return Err("Explicit bounded web source networks required");}
        if self.profile.is_empty() || self.profile.len()>31 || !self.profile.bytes().all(|c|c.is_ascii_lowercase()||c.is_ascii_digit()||b"_-".contains(&c)) {return Err("Invalid telemetry SLA profile");}
        self.allowed_sources.iter().map(|s|Network::parse(s)).collect()
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn disabled_is_default_without_sources() {let s=Settings::default();assert!(!s.enabled);assert!(s.validate().unwrap().is_empty());}
    #[test] fn private_sources_are_canonical_and_bounded() {
        assert!(Network::parse("192.168.50.0/24").unwrap().contains("192.168.50.101".parse().unwrap()));
        for n in ["0.0.0.0/0","8.8.8.0/24","172.0.0.0/8","192.168.50.2/24","127.0.0.1","::1/128"] {assert!(Network::parse(n).is_err(),"{n}");}
    }
    #[test] fn enabled_requires_explicit_safe_settings() {
        let mut s=Settings{enabled:true,..Default::default()};assert!(s.validate().is_err());s.allowed_sources=vec!["192.168.50.0/24".into()];assert!(s.validate().is_ok());
        s.token_file="/secrets/api-password".into();assert!(s.validate().is_err());s.token_file="/secrets/web-token".into();s.history_points=601;assert!(s.validate().is_err());
    }
}
