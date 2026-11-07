//! One routing cycle with an injected clock, RouterOS client and RAM heartbeat.
//! Production uses monomorphized adapters; tests need no CHR, files or delays.
use crate::{
    api::Api,
    model::{self, Config, Intent, Metrics},
};
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    io,
    time::{Duration, Instant},
};

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    #[default]
    Shadow,
    Active,
}
impl Mode {
    pub fn name(self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Active => "active",
        }
    }
}
pub trait Client {
    fn active_config(&mut self) -> io::Result<String>;
    fn write_intent(&mut self, name: &str, contents: &str) -> io::Result<()>;
}
impl Client for Api {
    fn active_config(&mut self) -> io::Result<String> {
        Api::active_config(self)
    }
    fn write_intent(&mut self, name: &str, contents: &str) -> io::Result<()> {
        Api::write_intent(self, name, contents)
    }
}
#[derive(Debug)]
pub struct Outcome {
    pub state: String,
    pub selected: Option<BTreeMap<String, String>>,
}
impl Outcome {
    fn waiting(message: &str) -> Self {
        Self {
            state: message.into(),
            selected: None,
        }
    }
}
pub struct Engine {
    mode: Mode,
    instance: String,
    config: Option<Config>,
    config_key: String,
    last_written: Option<(String, u64, BTreeMap<String, String>)>,
    last_claim: Option<Instant>,
    last_observed: Option<(u64, Instant)>,
    seq: u64,
}
fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}
impl Engine {
    pub fn new(mode: Mode, instance: String) -> Self {
        Self {
            mode,
            instance,
            config: None,
            config_key: String::new(),
            last_written: None,
            last_claim: None,
            last_observed: None,
            seq: 0,
        }
    }
    pub fn reset_session(&mut self) {
        self.config = None;
        self.config_key.clear();
        self.last_written = None;
    }
    pub fn step(
        &mut self,
        client: &mut impl Client,
        metrics: &Metrics,
        mut clock: impl FnMut() -> Instant,
        mut heartbeat: impl FnMut() -> io::Result<()>,
    ) -> Result<Outcome, Box<dyn std::error::Error>> {
        let now = clock();
        if let Some((uptime, since)) = self.last_observed {
            if uptime == metrics.uptime_seconds
                && now.saturating_duration_since(since) > Duration::from_secs(10)
            {
                return Err(invalid("Router controller telemetry stalled").into());
            }
        }
        if self
            .last_observed
            .is_none_or(|(uptime, _)| uptime != metrics.uptime_seconds)
        {
            self.last_observed = Some((metrics.uptime_seconds, now));
        }
        let key = metrics
            .container
            .as_ref()
            .map(|b| format!("{}:{}:{}", b.boot_id, b.generation, metrics.revision))
            .unwrap_or_else(|| metrics.revision.clone());
        if self.config.is_none() || key != self.config_key {
            self.config = Some(serde_json::from_str(&client.active_config()?)?);
            self.config_key = key;
        }
        let cfg = self.config.as_ref().expect("configuration loaded above");
        let plan = model::choose(cfg, metrics)?;
        if self.mode == Mode::Active {
            let Some(bridge) = metrics.container.as_ref().filter(|b| b.protocol == 1) else {
                return Ok(Outcome::waiting(
                    "waiting for provisioned RouterOS bridge protocol1; no writes",
                ));
            };
            if !bridge.owner_instance.is_empty()
                && bridge.owner_instance != self.instance
                && bridge.lease_remaining_seconds > 0
            {
                return Ok(Outcome::waiting(
                    "another controller owns the live lease; no writes or heartbeat",
                ));
            }
            if bridge.lease_remaining_seconds == 0 {
                heartbeat()?;
                return Ok(Outcome::waiting(
                    "waiting for RAM heartbeat lease; no intent writes",
                ));
            }
            let changed = self
                .last_written
                .as_ref()
                .is_none_or(|(boot, generation, selected)| {
                    boot != &bridge.boot_id || *generation != bridge.generation || selected != &plan
                });
            let retry_claim = bridge.owner_instance.is_empty()
                && self.last_claim.is_none_or(|since| {
                    now.saturating_duration_since(since) >= Duration::from_secs(6)
                });
            if changed || retry_claim {
                self.seq = self
                    .seq
                    .checked_add(1)
                    .ok_or_else(|| invalid("Intent sequence exhausted"))?;
                let intent = Intent {
                    protocol: 1,
                    instance: &self.instance,
                    seq: self.seq,
                    boot_id: &bridge.boot_id,
                    generation: bridge.generation,
                    observed_uptime: metrics.uptime_seconds,
                    revision: &cfg.revision,
                    selected: &plan,
                    release: false,
                };
                client.write_intent(&bridge.intent_file, &serde_json::to_string(&intent)?)?;
                self.last_written = Some((bridge.boot_id.clone(), bridge.generation, plan.clone()));
                self.last_claim = Some(clock());
            }
            heartbeat()?;
        }
        Ok(Outcome {
            state: format!("{}:{}", self.mode.name(), serde_json::to_string(&plan)?),
            selected: Some(plan),
        })
    }
}
#[cfg(test)]
#[path = "../tests/unit/engine.rs"]
mod tests;
