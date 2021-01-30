# Supported Devices:
# - Curtains that speaks Tuya Protocol
# - Bulbs that speaks Tuya Protocol
# - Sensor: I only have this NEO ZigBeeWirelessTuya.. works with this one

GATHER_DEVICES = {
    'rack_sensor': {
        'protocol': '3.3',
        'deviceid': 'from_tinytuya',
        'localkey': 'from_tinytuya',
        'ip': 'from_tinytuya_or_ur_dhcp'
    },
    'living_curtains': {
        'protocol': '3.3',
        'deviceid': 'from_tinytuya',
        'localkey': 'from_tinytuya',
        'ip': 'from_tinytuya_or_ur_dhcp'
    },
    'pool_bulb': {
        'protocol': '3.3',
        'deviceid': 'from_tinytuya',
        'localkey': 'from_tinytuya',
        'ip': 'from_tinytuya_or_ur_dhcp'
    }
}
