"""Metadata inventory for known controller families; never opens TTYs."""
import json
import subprocess
from controller_protocols import IDENTITIES, select_endpoints
from hdx_touch_probe import usb_device_tree, registry_children

# AquaMai 1.8.59-g4b5bd13: provider signatures and helper IL checked against
# the bundled 1.9.20 contract. This is an API build, not an HDD version gate.
ADDITIONAL_INPUT_APIS = {'7d447c328852f68a1dd1784ec6eba6c46f5a84fd9f0d933e2f9435e6aac9c87c'}


def inventory(runtime):
    rows = []; errors = []
    try:
        result = subprocess.run([str(runtime/'helpers/controller-hid'), '--inventory'],
                                capture_output=True, timeout=5, check=True)
        raw = json.loads(result.stdout)
        if not isinstance(raw, list) or len(raw) > 64 or any(not isinstance(r, dict) for r in raw):
            raise ValueError('Invalid controller inventory')
        rows = select_endpoints(raw)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as error:
        errors.append('HID 设备查询未完成：' + type(error).__name__)
    try:
        tree = usb_device_tree()
        from adx_serial_touch import endpoints
        rows.extend(endpoints(tree))
        def walk(node):
            vid, pid = node.get('idVendor'), node.get('idProduct')
            if (vid, pid) in IDENTITIES or (vid, pid) == (0xca3, 0x21):
                profile, player = IDENTITIES.get((vid, pid), ('hdx', 0))
                # No serial numbers or location identifiers in shared diagnostics.
                if not any(r['vendor'] == vid and r['product'] == pid for r in rows):
                    rows.append(dict(id='usb-' + str(node.get('IORegistryEntryID', len(rows))),
                        vendor=vid, product=pid, name=node.get('USB Product Name', profile), profile=profile,
                        player=player, channels=['buttons', 'touch', 'led', 'reader'] if profile == 'hdx' else [],
                        status='verifiedProfile' if profile == 'hdx' else 'unsupported',
                        detail='HDX 02 已有实机验证' if profile == 'hdx' else '未发现已匹配的 HID 输入接口；可能使用 WinUSB 或串口'))
            for child in registry_children(node): walk(child)
        for node in tree: walk(node)
        for player in (0, 1):
            candidates = [d for d in rows if d['status'] == 'candidate' and d['player'] == player]
            if len(candidates) > 1:
                for d in candidates: d.update(status='ambiguous', detail='同一玩家有多个输入接口，请只保留一台')
    except (OSError, RuntimeError) as error:
        errors.append(str(error))
    return dict(devices=rows, errors=errors)


def public_inventory(value):
    return dict(devices=[{k: v for k, v in d.items() if k not in ('descriptor', 'reportID', 'port')}
                         for d in value['devices']], errors=value['errors'])


def game_api_verified(runtime, package):
    """Check the actual public ABI, including renamed/packed provider DLLs.

    This proves static input compatibility, never physical device validation.
    Known fingerprints are only a fallback for previously audited packages.
    """
    from storage import digest
    from managed_mods import inspect_mods
    report = inspect_mods(package)
    if len(report['inputProviders']) > 1: return False
    if len(report['inputProviders']) == 1 and not report['issues']: return True
    try:
        manifest=json.loads((runtime/'manifest.json').read_text())
        actual=digest(package/'Mods/AquaMai.dll')
        return actual in ADDITIONAL_INPUT_APIS or any(profile.get('fingerprints',{}).get('Mods/AquaMai.dll')==actual
                   for profile in manifest.get('compatibility_profiles',[]))
    except (OSError,ValueError,TypeError):return False
