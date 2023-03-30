# 💡 Yeelight Pro for Home Assistant


<a name="installing"></a>
## Installation

#### Method 1: [HACS (**Click to install**)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hasscc&repository=yeelight-pro&category=integration)

#### Method 2: Manually install via Samba / SFTP
> [Download](https://github.com/hasscc/yeelight-pro/archive/main.zip) and copy `custom_components/yeelight_pro` folder to `custom_components` folder in your HomeAssistant config folder

#### Method 3: Onkey shell via SSH / Terminal & SSH add-on
```shell
wget -q -O - https://hacs.vip/get | HUB_DOMAIN=ghproxy.com/github.com DOMAIN=yeelight_pro REPO_PATH=hasscc/yeelight-pro ARCHIVE_TAG=main bash -
```

#### Method 4: shell_command service
1. Copy this code to file `configuration.yaml`
    ```yaml
    shell_command:
      update_yeelight_pro: |-
        wget -q -O - https://hacs.vip/get | HUB_DOMAIN=ghproxy.com/github.com DOMAIN=yeelight_pro REPO_PATH=hasscc/yeelight-pro ARCHIVE_TAG=main bash -
    ```
2. Restart HA core
3. Call this [`service: shell_command.update_yeelight_pro`](https://my.home-assistant.io/redirect/developer_call_service/?service=shell_command.update_yeelight_pro) in Developer Tools

