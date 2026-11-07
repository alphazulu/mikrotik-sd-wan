# MikroTik SD-WAN

[Русский](SD-WAN.md) | English

The controller runs on MikroTik: RouterOS RSC or an optional local Rust scratch
container with native fallback. External software handles setup, installation,
diagnostics and test observation; routing decisions remain on the device.

- [Roadmap](../ROADMAP.en.md).
- [Native implementation/configuration](NATIVE-CONTROLLER.en.md).
- Lab JSON: `config/sdwan.json`.
- Native source: `native/`.
- Windows configurator: `Configure-SD-WAN.cmd`.
- [Wizard: API connection, WAN selection and generation](CONFIGURATOR-WIZARD.en.md).

Early `config/sdwan-intent.json` remains as the initial design draft; the
controller does not load it.

Private runtime reports, credentials and device snapshots are not distributed.
[Reproduction](TESTING.en.md).
