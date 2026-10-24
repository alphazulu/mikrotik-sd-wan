//! Policy decisions use RouterOS' local probe/SLA telemetry. The RouterOS
//! actuator validates intent and keeps the native engine warm for fallback.
use std::collections::BTreeMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)] pub struct Config {
    pub schema_version: u32,
    pub revision: String,
    pub policies: Vec<Policy>,
}
#[derive(Debug, Deserialize)] pub struct Policy {
    pub name: String, pub profile: String, pub mode: String,
    pub wans: Vec<String>, pub allow_degraded: bool,
}
#[derive(Debug, Deserialize)] pub struct State { pub state: String }
#[derive(Debug, Deserialize)] pub struct Metrics {
    pub revision: String,
    pub uptime_seconds: u64,
    pub states: BTreeMap<String, State>,
    #[serde(default)] pub container: Option<Bridge>,
}
#[derive(Debug, Deserialize)] pub struct Bridge {
    pub protocol: u32, pub boot_id: String, pub generation: u64,
    pub intent_file: String,
    #[serde(default)] pub owner_instance: String,
    #[serde(default)] pub lease_remaining_seconds: u64,
}
#[derive(Debug, Serialize)] pub struct Intent<'a> {
    pub protocol: u32, pub instance: &'a str, pub seq: u64,
    pub boot_id: &'a str, pub generation: u64,
    pub observed_uptime: u64, pub revision: &'a str,
    pub selected: &'a BTreeMap<String,String>,
    pub release: bool,
}

pub fn choose(config: &Config, metrics: &Metrics) -> Result<BTreeMap<String,String>, &'static str> {
    if config.schema_version!=1 || config.revision!=metrics.revision { return Err("Configuration/telemetry version mismatch"); }
    if config.policies.is_empty() || config.policies.len()>64 { return Err("Policy count out of bounds"); }
    let mut result=BTreeMap::new();
    for policy in &config.policies {
        if policy.wans.is_empty() || policy.wans.len()>16 || !matches!(policy.mode.as_str(),"prefer"|"strict") || (policy.mode=="strict" && policy.wans.len()!=1) { return Err("Invalid policy WAN/mode"); }
        let find=|wanted:&str| policy.wans.iter().find(|wan| metrics.states.get(&format!("{}/{}",policy.profile,wan)).is_some_and(|s|s.state==wanted)).cloned();
        let selected=find("healthy").or_else(||if policy.allow_degraded {find("degraded")} else {None}).unwrap_or_else(||"none".into());
        if result.insert(policy.name.clone(),selected).is_some() { return Err("Duplicate policy name"); }
    }
    Ok(result)
}

#[cfg(test)] mod tests {
    use super::*;
    fn config() -> Config { serde_json::from_str(r#"{"schema_version":1,"revision":"fixture","policies":[{"name":"voice","profile":"voice","mode":"prefer","wans":["wan1","wan2"],"allow_degraded":false},{"name":"strict","profile":"voice","mode":"strict","wans":["wan1"],"allow_degraded":false}]}"#).unwrap() }
    fn metrics(a:&str,b:&str)->Metrics { Metrics{revision:"fixture".into(),uptime_seconds:1,states:BTreeMap::from([("voice/wan1".into(),State{state:a.into()}),("voice/wan2".into(),State{state:b.into()})]),container:None} }
    #[test] fn failover_strict_and_priority() {
        let c=config();assert_eq!(choose(&c,&metrics("healthy","healthy")).unwrap()["voice"],"wan1");
        let p=choose(&c,&metrics("down","healthy")).unwrap();assert_eq!(p["voice"],"wan2");assert_eq!(p["strict"],"none");
    }
    #[test] fn degraded_requires_explicit_permission_and_never_beats_healthy() {
        let mut c=config();assert_eq!(choose(&c,&metrics("degraded","down")).unwrap()["voice"],"none");
        c.policies[0].allow_degraded=true;
        assert_eq!(choose(&c,&metrics("degraded","down")).unwrap()["voice"],"wan1");
        assert_eq!(choose(&c,&metrics("degraded","healthy")).unwrap()["voice"],"wan2");
    }
    #[test] fn unknown_recovering_and_missing_metrics_stay_closed() {
        let p=choose(&config(),&metrics("unknown","recovering")).unwrap();assert!(p.values().all(|v|v=="none"));
    }
    #[test] fn mismatched_revision_rejected() { let mut m=metrics("healthy","healthy");m.revision="old".into();assert!(choose(&config(),&m).is_err()); }
    #[test] fn strict_with_backup_rejected() { let mut c=config();c.policies[1].wans.push("wan2".into());assert!(choose(&c,&metrics("healthy","healthy")).is_err()); }
}
