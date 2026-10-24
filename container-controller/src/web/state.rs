//! Bounded RAM data. This module has no filesystem or RouterOS mutation API.
use serde::{Deserialize,Deserializer,Serialize};
use serde::de::{self,MapAccess,SeqAccess,Visitor};
use std::collections::{BTreeMap,BTreeSet,VecDeque};
use std::fmt;
use std::time::{Duration,Instant};

pub const MAX_RAW:usize=262144;
pub const EVENT_CAP:usize=128;

#[derive(Clone,Debug,Default,PartialEq,Eq,PartialOrd,Ord,Serialize)]
pub struct Text<const N:usize>(pub String);
impl<'de,const N:usize> Deserialize<'de> for Text<N> {
    fn deserialize<D:Deserializer<'de>>(d:D)->Result<Self,D::Error> {
        struct V<const N:usize>;
        impl<'de,const N:usize> Visitor<'de> for V<N> {
            type Value=Text<N>;
            fn expecting(&self,f:&mut fmt::Formatter)->fmt::Result{write!(f,"bounded text")}
            fn visit_str<E:de::Error>(self,s:&str)->Result<Self::Value,E>{if s.len()>N {Err(E::custom("text limit exceeded"))} else {Ok(Text(s.to_owned()))}}
        }
        d.deserialize_str(V::<N>)
    }
}
#[derive(Clone,Debug)] pub struct Map<T,const N:usize>(pub BTreeMap<String,T>);
impl<T,const N:usize> Default for Map<T,N>{fn default()->Self{Self(BTreeMap::new())}}
impl<'de,T:Deserialize<'de>,const N:usize> Deserialize<'de> for Map<T,N>{
    fn deserialize<D:Deserializer<'de>>(d:D)->Result<Self,D::Error>{
        struct V<T,const N:usize>(std::marker::PhantomData<T>);
        impl<'de,T:Deserialize<'de>,const N:usize> Visitor<'de> for V<T,N>{
            type Value=Map<T,N>;
            fn expecting(&self,f:&mut fmt::Formatter)->fmt::Result{write!(f,"bounded object")}
            fn visit_map<A:MapAccess<'de>>(self,mut a:A)->Result<Self::Value,A::Error>{
                let mut out=BTreeMap::new();
                while let Some(k)=a.next_key::<Text<64>>()? {
                    if out.len()>=N || out.contains_key(&k.0){return Err(de::Error::custom("object limit or duplicate key"));}
                    out.insert(k.0,a.next_value()?);
                }
                Ok(Map(out))
            }
            fn visit_seq<A:SeqAccess<'de>>(self,mut a:A)->Result<Self::Value,A::Error>{
                if a.next_element::<de::IgnoredAny>()?.is_some(){return Err(de::Error::custom("only an empty legacy array is allowed"));}
                Ok(Map(BTreeMap::new()))
            }
        }
        d.deserialize_any(V::<T,N>(std::marker::PhantomData))
    }
}
#[derive(Clone,Debug,Default)] pub struct List<T,const N:usize>(pub Vec<T>);
impl<'de,T:Deserialize<'de>,const N:usize> Deserialize<'de> for List<T,N>{
    fn deserialize<D:Deserializer<'de>>(d:D)->Result<Self,D::Error>{
        struct V<T,const N:usize>(std::marker::PhantomData<T>);
        impl<'de,T:Deserialize<'de>,const N:usize> Visitor<'de> for V<T,N>{
            type Value=List<T,N>;
            fn expecting(&self,f:&mut fmt::Formatter)->fmt::Result{write!(f,"bounded list")}
            fn visit_seq<A:SeqAccess<'de>>(self,mut a:A)->Result<Self::Value,A::Error>{
                let mut out=Vec::new();
                while let Some(v)=a.next_element()? {if out.len()>=N{return Err(de::Error::custom("list limit exceeded"));}out.push(v);}
                Ok(List(out))
            }
        }
        d.deserialize_seq(V::<T,N>(std::marker::PhantomData))
    }
}

#[derive(Clone,Copy,Debug,Default,Deserialize,Serialize,PartialEq,Eq)]
#[serde(rename_all="lowercase")]
pub enum Quality {Healthy,Degraded,Down,Recovering,#[default] #[serde(other)] Unknown}
impl Quality {fn code(self)->u8{match self{Self::Unknown=>0,Self::Healthy=>1,Self::Degraded=>2,Self::Down=>3,Self::Recovering=>4}}}
#[derive(Clone,Debug,Deserialize)] pub struct State {pub state:Quality}
#[derive(Clone,Debug,Default,Deserialize)]
#[serde(default)]
pub struct Sample {
    pub interface:Text<256>,pub address:Text<64>,pub rtt_us:Option<u32>,pub jitter_us:Option<u32>,
    pub loss_basis_points:Option<u16>,pub link_ready:bool,pub stale:bool,pub warming:bool,
}
#[derive(Clone,Debug,Default,Deserialize)]
#[serde(default)]
pub struct Bridge {pub active:bool,pub boot_id:Text<64>,pub generation:u64}
#[derive(Clone,Debug,Default,Deserialize)]
#[serde(default)]
pub struct NativeEvent {pub seq:u64,pub uptime_seconds:u64,#[serde(rename="type")] pub kind:Text<32>,pub policy:Text<64>,pub wan:Text<31>,pub revision:Text<320>,pub from:Text<64>,pub to:Text<64>,pub reason:Text<512>}
#[derive(Clone,Debug,Deserialize)]
pub struct Update {
    pub uptime_seconds:u64,pub revision:Text<320>,
    #[serde(default)] pub backend:Text<32>,
    #[serde(default)] pub container:Option<Bridge>,
    #[serde(default)] pub samples:Map<Sample,16>,
    #[serde(default)] pub selected:Map<Text<31>,64>,
    #[serde(default)] pub states:Map<State,1024>,
    #[serde(default)] pub events:List<NativeEvent,100>,
}
impl Update {
    pub fn parse(raw:&str)->Result<Self,()> {
        if raw.len()>MAX_RAW{return Err(());}
        let value:Self=serde_json::from_str(raw).map_err(|_|())?;
        let ident=|s:&str|!s.is_empty()&&s.len()<=31&&s.bytes().all(|c|c.is_ascii_lowercase()||c.is_ascii_digit()||b"_-".contains(&c));
        if value.samples.0.keys().chain(value.selected.0.keys()).any(|s|!ident(s)) || value.states.0.keys().any(|s|s.split_once('/').is_none_or(|(a,b)|!ident(a)||!ident(b))) {return Err(());}
        if value.samples.0.values().any(|s|s.loss_basis_points.is_some_and(|n|n>10000)){return Err(());}
        Ok(value)
    }
}

#[derive(Clone,Copy,Debug,Serialize)]
pub struct Point(pub u64,pub Option<u32>,pub Option<u32>,pub Option<u16>,pub Option<u64>,pub Option<u64>,pub u8,pub u8);
#[derive(Clone,Debug)] pub struct Counter {pub at:Instant,pub rx:u64,pub tx:u64}
pub type Counters=BTreeMap<String,Counter>;
pub fn rate(now:u64,old:u64,elapsed:Duration)->Option<u64>{
    let delta=now.checked_sub(old)?;let nanos=elapsed.as_nanos();if nanos==0{return None;}
    u64::try_from((delta as u128)*8_000_000_000u128/nanos).ok()
}
#[derive(Clone,Default,Serialize)] pub struct Resources {pub rss_bytes:Option<u64>,pub cpu_ticks:Option<u64>,pub write_bytes:Option<u64>}
#[derive(Clone,Serialize)] pub struct Event {pub seq:u64,pub uptime_seconds:u64,#[serde(rename="type")] pub kind:String,pub policy:String,pub from:String,pub to:String,pub reason:String}
#[derive(Clone,Serialize)] pub struct Wan {
    pub name:String,pub interface:String,pub address:Option<String>,pub state:Quality,
    pub rtt_us:Option<u32>,pub jitter_us:Option<u32>,pub loss_basis_points:Option<u16>,
    pub link_ready:bool,pub stale:bool,pub warming:bool,pub rx_bps:Option<u64>,pub tx_bps:Option<u64>,
    pub observed_seconds:u64,pub unhealthy_seconds:u64,
}
#[derive(Clone,Serialize)] pub struct Policy {pub name:String,pub selected:String,pub transitions:u64}
#[derive(Clone,Serialize)] pub struct Current {pub uptime_seconds:u64,pub revision:String,pub actor:&'static str,pub profile:String,pub wans:Vec<Wan>,pub policies:Vec<Policy>,pub qualities:BTreeMap<String,Quality>}
#[derive(Clone,Serialize)] pub struct Status {
    pub schema:u8,pub epoch:u64,pub age_seconds:Option<u64>,pub stale:bool,pub current:Option<Current>,
    pub sample_seconds:u64,pub history_capacity:usize,pub history_points:usize,pub events:usize,
    pub observer_available:bool,pub invalid_snapshots:u64,pub resources:Resources,
}
#[derive(Clone,Serialize)] pub struct History {pub schema:u8,pub epoch:u64,pub columns:[&'static str;8],pub states:[&'static str;5],pub wans:BTreeMap<String,Vec<Point>>}
#[derive(Clone,Serialize)] pub struct Events {pub epoch:u64,pub events:Vec<Event>}
#[derive(Clone,Serialize)] pub struct Export {pub history:History,pub events:Events}
struct WanStore {interface:String,points:VecDeque<Point>,counter:Option<Counter>,rx:Option<u64>,tx:Option<u64>,observed:u64,unhealthy:u64}

pub struct Store {
    profile:String,interval:u64,capacity:usize,epoch_key:Option<(String,u64,String)>,epoch:u64,
    current:Option<Current>,advanced:Option<Instant>,last_uptime:Option<u64>,last_sample:Option<u64>,
    wans:BTreeMap<String,WanStore>,events:VecDeque<Event>,seq:u64,native_seq:u64,
    transitions:BTreeMap<String,u64>,invalid:u64,observer_available:bool,pub resources:Resources,
}
fn text(value:&str,api_secret:&str,web_secret:&str,limit:usize)->String {
    let mut s:String=value.chars().map(|c|if c.is_control(){' '}else{c}).collect();
    for secret in [api_secret,web_secret]{if !secret.is_empty(){s=s.replace(secret,"[redacted]");}}
    if s.len()>limit{let mut end=limit;while !s.is_char_boundary(end){end-=1;}s.truncate(end);}
    s
}
impl Store {
    pub fn new(profile:String,interval:u64,capacity:usize)->Self {
        Self{profile,interval,capacity:capacity.clamp(12,600),epoch_key:None,epoch:0,current:None,advanced:None,last_uptime:None,last_sample:None,wans:BTreeMap::new(),events:VecDeque::with_capacity(EVENT_CAP),seq:0,native_seq:0,transitions:BTreeMap::new(),invalid:0,observer_available:false,resources:Resources::default()}
    }
    pub fn invalid(&mut self){self.invalid=self.invalid.saturating_add(1);}
    pub fn epoch_changed(&self,value:&Update)->bool{
        self.epoch_key.as_ref().is_none_or(|(boot,generation,revision)|boot!=&value.container.as_ref().map(|b|b.boot_id.0.as_str()).unwrap_or("")||*generation!=value.container.as_ref().map(|b|b.generation).unwrap_or(0)||revision!=&value.revision.0)||self.last_uptime.is_some_and(|old|value.uptime_seconds<old)
    }
    fn event(&mut self,mut event:Event){self.seq=self.seq.saturating_add(1);event.seq=self.seq;if self.events.len()==EVENT_CAP{self.events.pop_front();}self.events.push_back(event);}
    pub fn ingest(&mut self,value:Update,at:Instant,counters:Option<&Counters>,api_secret:&str,web_secret:&str){
        let key=(value.container.as_ref().map(|b|b.boot_id.0.clone()).unwrap_or_default(),value.container.as_ref().map(|b|b.generation).unwrap_or(0),value.revision.0.clone());
        let reset=self.epoch_key.as_ref()!=Some(&key)||self.last_uptime.is_some_and(|old|value.uptime_seconds<old);
        if reset {
            self.epoch=self.epoch.saturating_add(1);self.epoch_key=Some(key);self.wans.clear();self.events.clear();self.seq=0;self.native_seq=0;self.transitions.clear();self.current=None;self.last_sample=None;self.last_uptime=None;
            self.event(Event{seq:0,uptime_seconds:value.uptime_seconds,kind:"epoch".into(),policy:String::new(),from:String::new(),to:String::new(),reason:"History reset for router/config epoch".into()});
        }
        let initial=self.current.is_none();let delta=self.last_uptime.and_then(|old|value.uptime_seconds.checked_sub(old)).filter(|d|*d<=10).unwrap_or(0);
        if self.last_uptime!=Some(value.uptime_seconds){self.advanced=Some(at);}
        let sample=self.last_sample.is_none_or(|old|value.uptime_seconds.saturating_sub(old)>=self.interval);
        let mut event_policies=BTreeSet::new();
        if value.events.0.iter().map(|e|e.seq).max().is_some_and(|last|last<self.native_seq){self.native_seq=0;}
        for e in value.events.0.iter().filter(|e|e.seq>self.native_seq).cloned().collect::<Vec<_>>() {
            self.native_seq=self.native_seq.max(e.seq);
            if !e.revision.0.is_empty()&&e.revision.0!=value.revision.0{continue;}
            if e.kind.0=="policy" && !initial && !e.from.0.is_empty(){let n=self.transitions.entry(e.policy.0.clone()).or_default();*n=n.saturating_add(1);event_policies.insert(e.policy.0.clone());}
            self.event(Event{seq:0,uptime_seconds:e.uptime_seconds,kind:text(&e.kind.0,api_secret,web_secret,16),policy:text(if e.policy.0.is_empty(){&e.wan.0}else{&e.policy.0},api_secret,web_secret,64),from:text(&e.from.0,api_secret,web_secret,32),to:text(&e.to.0,api_secret,web_secret,32),reason:text(&e.reason.0,api_secret,web_secret,192)});
        }
        let qualities:BTreeMap<String,Quality>=value.states.0.iter().map(|(k,v)|(k.clone(),v.state)).collect();
        let mut current_wans=Vec::with_capacity(value.samples.0.len());
        self.wans.retain(|name,_|value.samples.0.contains_key(name));
        for (name,s) in &value.samples.0 {
            let quality=if !s.link_ready{Quality::Down}else if s.stale{Quality::Unknown}else if s.warming{Quality::Recovering}else{qualities.get(&format!("{}/{name}",self.profile)).copied().unwrap_or_default()};
            let row=self.wans.entry(name.clone()).or_insert_with(||WanStore{interface:s.interface.0.clone(),points:VecDeque::with_capacity(self.capacity),counter:None,rx:None,tx:None,observed:0,unhealthy:0});
            if row.interface!=s.interface.0 {row.interface=s.interface.0.clone();row.counter=None;row.rx=None;row.tx=None;row.points.clear();row.observed=0;row.unhealthy=0;}
            if let Some(old)=self.current.as_ref().and_then(|c|c.wans.iter().find(|w|w.name==*name)).filter(|w|w.interface==s.interface.0&&!w.stale&&w.state!=Quality::Unknown) {
                row.observed=row.observed.saturating_add(delta);if old.state!=Quality::Healthy{row.unhealthy=row.unhealthy.saturating_add(delta);}
            }
            match counters.and_then(|c|c.get(&s.interface.0)) {
                Some(now)=>{
                    if let Some(old)=&row.counter {if now.at!=old.at {let elapsed=now.at.saturating_duration_since(old.at);row.rx=rate(now.rx,old.rx,elapsed);row.tx=rate(now.tx,old.tx,elapsed);}}
                    row.counter=Some(now.clone());
                },
                None=>{row.counter=None;row.rx=None;row.tx=None;}
            }
            let fresh=s.link_ready&&!s.stale&&!s.warming;let loss=if fresh{s.loss_basis_points}else{None};
            let rtt=if !fresh||loss==Some(10000){None}else{s.rtt_us};let jitter=if !fresh||loss==Some(10000){None}else{s.jitter_us};
            if sample {if row.points.len()==self.capacity{row.points.pop_front();}row.points.push_back(Point(value.uptime_seconds,rtt,jitter,loss,row.rx,row.tx,quality.code(),(s.link_ready as u8)|((s.stale as u8)<<1)|((s.warming as u8)<<2)));}
            current_wans.push(Wan{name:name.clone(),interface:text(&s.interface.0,api_secret,web_secret,256),address:s.address.0.parse::<std::net::Ipv4Addr>().ok().map(|ip|ip.to_string()),state:quality,rtt_us:rtt,jitter_us:jitter,loss_basis_points:loss,link_ready:s.link_ready,stale:s.stale,warming:s.warming,rx_bps:row.rx,tx_bps:row.tx,observed_seconds:row.observed,unhealthy_seconds:row.unhealthy});
        }
        let mut policies=Vec::with_capacity(value.selected.0.len());
        self.transitions.retain(|name,_|value.selected.0.contains_key(name));
        for (name,selected) in &value.selected.0 {
            let changed=self.current.as_ref().and_then(|c|c.policies.iter().find(|p|p.name==*name)).is_some_and(|p|p.selected!=selected.0);
            if changed&&!event_policies.contains(name){
                let n=self.transitions.entry(name.clone()).or_default();*n=n.saturating_add(1);
                let from=self.current.as_ref().and_then(|c|c.policies.iter().find(|p|p.name==*name)).map(|p|p.selected.clone()).unwrap_or_default();
                self.event(Event{seq:0,uptime_seconds:value.uptime_seconds,kind:"policy".into(),policy:name.clone(),from,to:text(&selected.0,api_secret,web_secret,31),reason:"Observed policy selection changed".into()});
            }
            policies.push(Policy{name:name.clone(),selected:text(&selected.0,api_secret,web_secret,31),transitions:self.transitions.get(name).copied().unwrap_or(0)});
        }
        let actor=if value.backend.0=="container" {if value.container.as_ref().is_some_and(|b|b.active){"container"}else{"routeros-fallback"}}else{"routeros"};
        if let Some(from)=self.current.as_ref().map(|c|c.actor).filter(|old|*old!=actor){self.event(Event{seq:0,uptime_seconds:value.uptime_seconds,kind:"actor".into(),policy:String::new(),from:from.into(),to:actor.into(),reason:"Observed controller mode changed".into()});}
        self.current=Some(Current{uptime_seconds:value.uptime_seconds,revision:text(&value.revision.0,api_secret,web_secret,320),actor,profile:self.profile.clone(),wans:current_wans,policies,qualities});
        self.observer_available=counters.is_some();self.last_uptime=Some(value.uptime_seconds);if sample{self.last_sample=Some(value.uptime_seconds);}
    }
    pub fn status(&self,now:Instant)->Status {
        let age=self.advanced.map(|at|now.saturating_duration_since(at).as_secs());
        Status{schema:1,epoch:self.epoch,age_seconds:age,stale:age.is_none_or(|age|age>10),current:self.current.clone(),sample_seconds:self.interval,history_capacity:self.capacity,history_points:self.wans.values().map(|w|w.points.len()).max().unwrap_or(0),events:self.events.len(),observer_available:self.observer_available,invalid_snapshots:self.invalid,resources:self.resources.clone()}
    }
    pub fn history(&self,max:usize)->History {
        History{schema:1,epoch:self.epoch,columns:["uptime_seconds","rtt_us","jitter_us","loss_basis_points","rx_bps","tx_bps","state","flags"],states:["unknown","healthy","degraded","down","recovering"],wans:self.wans.iter().map(|(name,w)|(name.clone(),w.points.iter().skip(w.points.len().saturating_sub(max.min(600))).copied().collect())).collect()}
    }
    pub fn events(&self,since:u64)->Events {Events{epoch:self.epoch,events:self.events.iter().filter(|e|e.seq>since).cloned().collect()}}
    pub fn export(&self)->Export{Export{history:self.history(self.capacity),events:self.events(0)}}
}

#[cfg(test)] mod tests {
    use super::*;
    fn update(u:u64)->Update {Update::parse(&format!(r#"{{"uptime_seconds":{u},"revision":"test","samples":{{"wan1":{{"interface":"ether2","rtt_us":1000,"jitter_us":10,"loss_basis_points":0,"link_ready":true}}}},"states":{{"default/wan1":{{"state":"healthy"}}}},"selected":{{"default":"wan1"}}}}"#)).unwrap()}
    #[test] fn bounds_reject_extra_rows_long_text_and_duplicate_names(){
        let names=(0..17).map(|n|format!("\"wan{n}\":{{}}" )).collect::<Vec<_>>().join(",");
        assert!(Update::parse(&format!(r#"{{"uptime_seconds":1,"revision":"x","samples":{{{names}}}}}"#)).is_err());
        assert!(Update::parse(r#"{"uptime_seconds":1,"revision":"x","samples":{"wan1":{},"wan1":{}}}"#).is_err());
        assert!(Update::parse(&"x".repeat(MAX_RAW+1)).is_err());
    }
    #[test] fn history_is_bounded_and_epoch_reset_discards_old_rows(){
        let start=Instant::now();let mut s=Store::new("default".into(),5,12);
        for i in 0..100 {s.ingest(update(i*5),start+Duration::from_secs(i*5),None,"","");}
        assert_eq!(s.history(600).wans["wan1"].len(),12);assert_eq!(s.history(2).wans["wan1"].len(),2);
        let mut u=update(501);u.revision.0="new".into();s.ingest(u,start+Duration::from_secs(501),None,"","");assert_eq!(s.history(600).wans["wan1"].len(),1);assert_eq!(s.status(start).epoch,2);
    }
    #[test] fn no_new_uptime_becomes_stale_and_gaps_are_not_counted(){
        let start=Instant::now();let mut s=Store::new("default".into(),10,12);s.ingest(update(1),start,None,"","");s.ingest(update(1),start+Duration::from_secs(20),None,"","");assert!(s.status(start+Duration::from_secs(20)).stale);
        s.ingest(update(100),start+Duration::from_secs(100),None,"","");assert_eq!(s.status(start).current.unwrap().wans[0].observed_seconds,0);
    }
    #[test] fn counter_reset_unknown_values_and_secret_fields_are_safe(){
        assert_eq!(rate(200,100,Duration::from_secs(1)),Some(800));assert_eq!(rate(1,100,Duration::from_secs(1)),None);assert_eq!(rate(1,0,Duration::ZERO),None);
        let start=Instant::now();let mut s=Store::new("default".into(),5,12);let mut u=update(1);u.revision.0="api-fixture-secret".into();u.events.0.push(NativeEvent{seq:1,reason:Text("web-fixture-token api-fixture-secret".into()),..Default::default()});s.ingest(u,start,None,"api-fixture-secret","web-fixture-token");
        let data=serde_json::to_string(&(s.status(start),s.export())).unwrap();assert!(!data.contains("api-fixture-secret"));assert!(!data.contains("web-fixture-token"));assert!(data.contains("redacted"));assert!(data.contains("\"rx_bps\":null"));
    }
    #[test] fn packet_errors_do_not_clear_good_history(){
        let start=Instant::now();let mut s=Store::new("default".into(),5,12);s.ingest(update(1),start,None,"","");s.invalid();assert_eq!(s.status(start).history_points,1);assert_eq!(s.status(start).invalid_snapshots,1);
    }
    #[test] fn worst_case_export_fits_http_budget_and_ring_stops_growing(){
        let mut s=Store::new("default".into(),5,600);
        for n in 0..16 {
            let points=VecDeque::from(vec![Point(u64::MAX,Some(u32::MAX),Some(u32::MAX),Some(10000),Some(u64::MAX),Some(u64::MAX),4,7);600]);
            s.wans.insert(format!("wan{n}"),WanStore{interface:"ether2".into(),points,counter:None,rx:None,tx:None,observed:0,unhealthy:0});
        }
        for _ in 0..200{s.event(Event{seq:0,uptime_seconds:u64::MAX,kind:"\\".repeat(16),policy:"\\".repeat(64),from:"\\".repeat(32),to:"\\".repeat(32),reason:"\\".repeat(192)});}
        assert_eq!(s.events.len(),EVENT_CAP);
        let bytes=serde_json::to_vec(&s.export()).unwrap();assert!(bytes.len()+2048<1048576,"{}",bytes.len());
        assert_eq!(s.history(600).wans.values().map(Vec::len).sum::<usize>(),9600);
    }
    #[test] fn old_revision_events_are_excluded_and_fallback_is_observed(){
        let start=Instant::now();let mut s=Store::new("default".into(),5,12);let mut u=update(1);u.backend.0="container".into();u.container=Some(Bridge{active:true,..Default::default()});u.events.0.push(NativeEvent{seq:1,revision:Text("old-config".into()),reason:Text("must-not-appear".into()),..Default::default()});s.ingest(u.clone(),start,None,"","");
        u.uptime_seconds=2;u.container.as_mut().unwrap().active=false;s.ingest(u,start+Duration::from_secs(1),None,"","");
        let events=s.events(0);assert_eq!(events.events.len(),2);assert_eq!(events.events[1].kind,"actor");assert_eq!(events.events[1].to,"routeros-fallback");assert!(!serde_json::to_string(&events).unwrap().contains("must-not-appear"));
    }
}
