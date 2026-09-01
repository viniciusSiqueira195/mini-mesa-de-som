"""List every audio endpoint currently reported by Windows and PortAudio."""

from __future__ import annotations

import sounddevice as sd


def main() -> None:
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    for host_id, host in enumerate(host_apis):
        api_devices = [
            (device_id, device)
            for device_id, device in enumerate(devices)
            if device["hostapi"] == host_id
        ]
        if not api_devices:
            continue
        print(f'\n{host["name"]}')
        for device_id, device in api_devices:
            roles = []
            if device["max_input_channels"] > 0:
                roles.append(f'entrada ({device["max_input_channels"]} canais)')
            if device["max_output_channels"] > 0:
                roles.append(f'saída ({device["max_output_channels"]} canais)')
            print(f'  ID atual {device_id}: {device["name"]} - {", ".join(roles)}')


if __name__ == "__main__":
    main()
