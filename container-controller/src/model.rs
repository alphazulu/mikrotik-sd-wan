//! Policy decisions use RouterOS' local probe/SLA telemetry. The RouterOS
//! actuator validates intent and keeps the native engine warm for fallback.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Deserialize)]
pub struct Config {
    pub schema_version: u32,
    pub revision: String,
    pub policies: Vec<Policy>,
    #[serde(default)]
    pub wans: Vec<Wan>,
}
#[derive(Debug, Deserialize)]
pub struct Wan {
    pub name: String,
    #[serde(default = "enabled")]
    pub admin_state: String,
}
fn enabled() -> String {
    "enabled".into()
}
#[derive(Debug, Deserialize)]
pub struct Policy {
    pub name: String,
    pub profile: String,
    pub mode: String,
    pub wans: Vec<String>,
    pub allow_degraded: bool,
}
#[derive(Debug, Deserialize)]
pub struct State {
    pub state: String,
}
#[derive(Debug, Deserialize)]
pub struct Metrics {
    pub revision: String,
    pub uptime_seconds: u64,
    pub states: BTreeMap<String, State>,
    #[serde(default)]
    pub container: Option<Bridge>,
}
#[derive(Debug, Deserialize)]
pub struct Bridge {
    pub protocol: u32,
    pub boot_id: String,
    pub generation: u64,
    pub intent_file: String,
    #[serde(default)]
    pub owner_instance: String,
    #[serde(default)]
    pub lease_remaining_seconds: u64,
}
#[derive(Debug, Serialize)]
pub struct Intent<'a> {
    pub protocol: u32,
    pub instance: &'a str,
    pub seq: u64,
    pub boot_id: &'a str,
    pub generation: u64,
    pub observed_uptime: u64,
    pub revision: &'a str,
    pub selected: &'a BTreeMap<String, String>,
    pub release: bool,
}

pub fn choose(
    config: &Config,
    metrics: &Metrics,
) -> Result<BTreeMap<String, String>, &'static str> {
    if config.schema_version != 1 || config.revision != metrics.revision {
        return Err("Configuration/telemetry version mismatch");
    }
    if config.policies.is_empty() || config.policies.len() > 64 {
        return Err("Policy count out of bounds");
    }
    let mut admission = BTreeMap::new();
    if config.wans.len() > 16 {
        return Err("WAN count out of bounds");
    }
    for wan in &config.wans {
        if !matches!(wan.admin_state.as_str(), "enabled" | "drain" | "down")
            || admission
                .insert(wan.name.as_str(), wan.admin_state == "enabled")
                .is_some()
        {
            return Err("Invalid WAN maintenance state");
        }
    }
    let mut result = BTreeMap::new();
    for policy in &config.policies {
        if policy.wans.is_empty()
            || policy.wans.len() > 16
            || !matches!(policy.mode.as_str(), "prefer" | "strict")
            || (policy.mode == "strict" && policy.wans.len() != 1)
        {
            return Err("Invalid policy WAN/mode");
        }
        let find = |wanted: &str| {
            policy
                .wans
                .iter()
                .find(|wan| {
                    (config.wans.is_empty() || admission.get(wan.as_str()) == Some(&true))
                        && metrics
                            .states
                            .get(&format!("{}/{}", policy.profile, wan))
                            .is_some_and(|s| s.state == wanted)
                })
                .cloned()
        };
        let selected = find("healthy")
            .or_else(|| {
                if policy.allow_degraded {
                    find("degraded")
                } else {
                    None
                }
            })
            .unwrap_or_else(|| "none".into());
        if result.insert(policy.name.clone(), selected).is_some() {
            return Err("Duplicate policy name");
        }
    }
    Ok(result)
}

#[cfg(test)]
#[path = "../tests/unit/model.rs"]
mod tests;
