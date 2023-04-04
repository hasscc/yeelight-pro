DOMAIN = 'yeelight_pro'
DEFAULT_NAME = 'Yeelight Pro'

CONF_GATEWAYS = 'gateways'
CONF_PID = 'pid'

SUPPORTED_DOMAINS = [
    'button',
    'sensor',
    'switch',
    'light',
    'number',
    'binary_sensor',
    'cover',
]

PID_GATEWAY = 1
PID_WIFI_PANEL = 2

GATEWAY_TYPES = {
    PID_GATEWAY: 'Gateway Pro (网关)',
    PID_WIFI_PANEL: 'Wifi Panel (全面屏)',
}
