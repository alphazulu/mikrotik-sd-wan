# RU/EN documentation conventions

[Русский](LANGUAGES.md) | English

User documentation is maintained in pairs: Russian `NAME.md` and English
`NAME.en.md` in the same directory. Existing Russian paths remain stable.
Each page starts with a link to its counterpart. `AGENTS.md`, source code, logs
and private handoff files are not translated user guides.

## Content of each pair

- Both versions describe the same behavior, limitations and validation status.
- Commands, field names, JSON values, paths and identifiers are not translated.
  UI labels match the application and may include an explanatory translation.
- Page prose uses its designated language. Do not append isolated English
  paragraphs to a Russian guide instead of updating the English counterpart.
- English pages link to English counterparts when available. Temporary links
  to untranslated pages are explicitly marked `RU`.
- Keep WAN, SLA, API, RSC, conntrack, Address List, WireGuard and OSPF identifiers.
  RTT and jitter use ms, loss uses %, and rates use Mbit/s. Label bytes, KiB/MiB
  and decimal MB explicitly rather than treating them as interchangeable.

## Status and evidence

The current summary is [CURRENT-STATUS.en.md](CURRENT-STATUS.en.md). Historical
reports retain their versions, commits and actual validation scope. Label design
documents as designs; do not describe a completed milestone as a current plan.
Releases, long acceptance and hardware recommendations each require their own checks.

Before publication, check pair completeness, equivalent meaning, relative links,
commands against the current CLI, numbers against reports, and absence of personal
data. A second filename alone does not establish translation quality. An unfinished
language cleanup must not be published as complete.
