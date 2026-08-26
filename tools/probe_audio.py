"""Diagnose which Windows host APIs can open the current audio devices."""

from __future__ import annotations

import sounddevice as sd


def main() -> None:
    def input_callback(_indata, _frames, _time_info, _status) -> None:
        return None

    def output_callback(outdata, _frames, _time_info, _status) -> None:
        outdata.fill(0)

    devices = sd.query_devices()
    host_apis = sd.query_hostapis()
    for host_id, host in enumerate(host_apis):
        inputs = [
            (index, device)
            for index, device in enumerate(devices)
            if device["hostapi"] == host_id
            and device["max_input_channels"] > 0
            and "fifine microphone" in device["name"].lower()
        ]
        outputs = [
            (index, device)
            for index, device in enumerate(devices)
            if device["hostapi"] == host_id
            and device["max_output_channels"] > 0
            and (
                "virtual audio cable" in device["name"].lower()
                or "virtual cable" in device["name"].lower()
            )
        ]
        if not inputs or not outputs:
            continue

        input_id, input_info = inputs[0]
        output_id, output_info = outputs[0]
        sample_rate = float(input_info["default_samplerate"])
        if sample_rate != float(output_info["default_samplerate"]):
            sample_rate = 48_000.0
        try:
            input_stream = sd.InputStream(
                device=input_id,
                samplerate=sample_rate,
                channels=min(2, int(input_info["max_input_channels"])),
                blocksize=512,
                dtype="float32",
                callback=input_callback,
            )
            output_stream = sd.OutputStream(
                device=output_id,
                samplerate=sample_rate,
                channels=min(2, int(output_info["max_output_channels"])),
                blocksize=512,
                dtype="float32",
                callback=output_callback,
            )
        except Exception as exc:
            print(f'{host["name"]}: FALHOU: {exc}')
        else:
            input_stream.close()
            output_stream.close()
            print(
                f'{host["name"]}: OK; entrada ID {input_id}; '
                f'saída ID {output_id}; {sample_rate:g} Hz'
            )


if __name__ == "__main__":
    main()
