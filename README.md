# 💡 Yeelight Pro for Home Assistant

Custom integration for controlling **Yeelight Pro** gateways and devices from Home Assistant.

- 🌓 Full support for **lights** (brightness, color temperature, RGB, transitions)
- 🌡️ **Climate** devices (AC via Yeelight Pro)
- 🪟 **Covers / curtains**
- 🔘 **Switches, buttons, panels, scenes**
- 👀 **Sensors** (motion, contact, illumination, etc.)
- 🧪 Debug services for sending raw commands and mocking incoming messages

---

## 🧩 Installation

### Method 1 — HACS (recommended)

> Requires HACS to be installed.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hasscc&repository=yeelight-pro&category=integration)

1. Open **HACS → Integrations → Three dots → Custom repositories**  
2. Add repository: `https://github.com/hasscc/yeelight-pro` with category **Integration**  
3. Find **Yeelight Pro** in HACS and click **Download**  
4. Restart Home Assistant  
5. Go to **Settings → Devices & Services → Add Integration → Yeelight Pro**

---

### Method 2 — Manual (Samba / SFTP)

1. [Download ZIP](https://github.com/hasscc/yeelight-pro/archive/main.zip)
2. Unpack and copy the folder:

   ```text
   custom_components/yeelight_pro
   ```
into your Home Assistant config/custom_components directory.
3. Restart Home Assistant.
4. Add integration via Settings → Devices & Services → Add Integration → Yeelight Pro.

⚙️ Configuration

The integration uses config flow, so you configure it from the UI:
1. Go to Settings → Devices & Services → Add Integration.
2. Find Yeelight Pro.
3. Enter your gateway host (e.g. 192.168.1.100).
4. Wait for the connection test to complete.
5. Once configured, all supported devices (lights, sensors, switches, etc.) will appear in Home Assistant.

If you previously used the original integration, you can:
* Keep your existing entities (same unique IDs where possible).
* Backup config/.storage/core.config_entries before experiments to be able to roll back.

🧪 Debug & Developer Services

Integration exposes two advanced services:

yeelight_pro.send_command

Send a raw command to the gateway and optionally show the result as a persistent notification.

Service data example:

```text
service: yeelight_pro.send_command
data:
  host: 192.168.1.100
  method: gateway_get.node
  params:
    id: 0
  throw: true
```

* host – gateway IP (or leave empty to send to the first configured gateway)
* method – API method (e.g. gateway_get.node, gateway_set.prop)
* params – JSON-like payload sent to the gateway
* throw – if true, result will be shown as a notification in HA

*yeelight_pro.mock_incoming_message*

Mock an incoming JSON message from the gateway. Useful to debug events / device decoding without real hardware event.

```text
service: yeelight_pro.mock_incoming_message
data:
  host: 192.168.1.100
  message: >
    {"id": 8218, "method": "gateway_post.event",
     "nodes": [{"params": {}, "value": "motion.false", "id": 301809111, "nt": 2}]}
```

You can also paste Python-dict style:

```text
message: >
  {'id': 8218, 'method': 'gateway_post.event',
   'nodes': [{'params': {}, 'value': 'motion.false', 'id': 301809111, 'nt': 2}]}
```

The integration will try json.loads first and then ast.literal_eval.

💡 Usage examples

Below are some real-world automations that show how to use Yeelight Pro devices in Home Assistant.

2. Using Yeelight Pro panel button events (example)

If you have a Yeelight Pro switch panel, the integration decodes button events into sensor entities with action attribute (e.g. button1_single, button1_double, etc.).

Example automation reacting on a panel click:

```text
alias: Toggle living room light from Yeelight panel
trigger:
  - platform: state
    entity_id: sensor.living_room_panel_action
    to: "button1_single"
condition: []
action:
  - service: light.toggle
    target:
      entity_id: light.living_room_main
mode: single
```

3. Simple climate control via Yeelight Pro AC

```text
alias: Set AC to cool when hot
trigger:
  - platform: numeric_state
    entity_id: sensor.living_room_temperature
    above: 26
condition: []
action:
  - service: climate.set_hvac_mode
    target:
      entity_id: climate.living_room_ac
    data:
      hvac_mode: cool
  - service: climate.set_temperature
    target:
      entity_id: climate.living_room_ac
    data:
      temperature: 23
mode: single
```