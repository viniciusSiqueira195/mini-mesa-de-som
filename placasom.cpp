#define NOMINMAX
#include <windows.h>
#include <tlhelp32.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <Functiondiscoverykeys_devpkey.h>
#include <wrl/client.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <fcntl.h>
#include <io.h>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#pragma comment(lib, "Ole32.lib")
#pragma comment(lib, "Mmdevapi.lib")
using Microsoft::WRL::ComPtr;

static std::mutex protocolMutex;
static void Protocol(const std::string& line) {
    std::lock_guard<std::mutex> lock(protocolMutex);
    std::cout << line << std::endl;
}
static std::string Clean(std::string s) {
    for (char& c : s) if (c == '\t' || c == '\r' || c == '\n') c = ' ';
    return s;
}
static void Check(HRESULT hr, const char* operation) {
    if (FAILED(hr)) {
        std::ostringstream s; s << operation << " (HRESULT 0x" << std::hex << static_cast<unsigned long>(hr) << ")";
        throw std::runtime_error(s.str());
    }
}
static std::string Utf8(const std::wstring& s) {
    if (s.empty()) return {};
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), nullptr, 0, nullptr, nullptr);
    if (!n) throw std::runtime_error("Nome de dispositivo Unicode invalido");
    std::string out(n, '\0');
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), out.data(), n, nullptr, nullptr);
    return out;
}
struct ComApartment {
    ComApartment() { Check(CoInitializeEx(nullptr, COINIT_MULTITHREADED), "CoInitializeEx"); }
    ~ComApartment() { CoUninitialize(); }
};
struct Handle {
    HANDLE value;
    explicit Handle(HANDLE h) : value(h) { if (!h || h == INVALID_HANDLE_VALUE) throw std::runtime_error("Falha ao criar handle"); }
    ~Handle() { CloseHandle(value); }
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
};
static ComPtr<IMMDeviceEnumerator> Enumerator() {
    ComPtr<IMMDeviceEnumerator> e;
    Check(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, IID_PPV_ARGS(&e)), "Enumerador de audio");
    return e;
}
static ComPtr<IMMDevice> Device(const std::wstring& id, EDataFlow expected) {
    auto e = Enumerator(); ComPtr<IMMDevice> d;
    Check(e->GetDevice(id.c_str(), &d), "Dispositivo selecionado indisponivel");
    DWORD state = 0; Check(d->GetState(&state), "Estado do dispositivo");
    if (!(state & DEVICE_STATE_ACTIVE)) throw std::runtime_error("Dispositivo selecionado desativado");
    ComPtr<IMMEndpoint> endpoint; Check(d.As(&endpoint), "Tipo do dispositivo");
    EDataFlow flow; Check(endpoint->GetDataFlow(&flow), "Fluxo do dispositivo");
    if (flow != expected) throw std::runtime_error("Tipo de dispositivo incorreto");
    return d;
}
static void ListDevices() {
    auto e = Enumerator();
    for (EDataFlow flow : {eCapture, eRender}) {
        ComPtr<IMMDeviceCollection> collection;
        Check(e->EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE, &collection), "Listar dispositivos");
        UINT count = 0; Check(collection->GetCount(&count), "Contar dispositivos");
        for (UINT i = 0; i < count; ++i) {
            ComPtr<IMMDevice> d; Check(collection->Item(i, &d), "Obter dispositivo");
            LPWSTR raw = nullptr; Check(d->GetId(&raw), "ID do dispositivo");
            std::wstring id(raw); CoTaskMemFree(raw);
            ComPtr<IPropertyStore> properties;
            Check(d->OpenPropertyStore(STGM_READ, &properties), "Propriedades do dispositivo");
            PROPVARIANT name; PropVariantInit(&name);
            HRESULT hr = properties->GetValue(PKEY_Device_FriendlyName, &name);
            std::wstring label = SUCCEEDED(hr) && name.vt == VT_LPWSTR && name.pwszVal ? name.pwszVal : id;
            PropVariantClear(&name);
            Protocol(std::string("DEVICE\t") + (flow == eCapture ? "capture\t" : "render\t") + Utf8(id) + "\t" + Clean(Utf8(label)));
        }
    }
}

// Suppress only descendants of another selected live PID, never unrelated PIDs.
static std::vector<DWORD> RootPids(const std::vector<DWORD>& input, const std::map<DWORD, DWORD>& parents) {
    std::set<DWORD> selected(input.begin(), input.end());
    std::vector<DWORD> roots;
    for (DWORD pid : selected) {
        DWORD current = pid; std::set<DWORD> seen{pid}; bool covered = false;
        while (true) {
            auto it = parents.find(current);
            if (it == parents.end() || !it->second || !seen.insert(it->second).second) break;
            current = it->second;
            if (selected.count(current)) { covered = true; break; }
        }
        if (!covered) roots.push_back(pid);
    }
    return roots;
}
static bool IsDescendantOf(DWORD pid, DWORD root, const std::map<DWORD, DWORD>& parents) {
    std::set<DWORD> seen;
    while (pid && seen.insert(pid).second) {
        if (pid == root) return true;
        auto it = parents.find(pid);
        if (it == parents.end()) return false;
        pid = it->second;
    }
    return false;
}

// WebView2's sandboxed AudioService can own render streams that Windows does
// not include when process loopback targets its native host. Capture those
// descendants directly, while keeping ordinary programs on their root PID.
static std::vector<DWORD> SelectedCaptureTargets(const std::vector<DWORD>& pids) {
    Handle snapshot(CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0));
    PROCESSENTRY32W entry{}; entry.dwSize = sizeof(entry);
    std::map<DWORD, DWORD> parents;
    std::map<DWORD, std::wstring> names;
    if (!Process32FirstW(snapshot.value, &entry)) throw std::runtime_error("Falha ao enumerar processos");
    do {
        parents[entry.th32ProcessID] = entry.th32ParentProcessID;
        names[entry.th32ProcessID] = entry.szExeFile;
    } while (Process32NextW(snapshot.value, &entry));
    if (GetLastError() != ERROR_NO_MORE_FILES) throw std::runtime_error("Falha ao terminar enumeracao de processos");
    for (DWORD pid : pids) if (!pid || !parents.count(pid)) throw std::runtime_error("Processo selecionado terminou antes da inicializacao");
    auto roots = RootPids(pids, parents);
    std::vector<DWORD> targets;
    for (DWORD root : roots) {
        std::vector<DWORD> webviews;
        for (const auto& [pid, name] : names) {
            if (_wcsicmp(name.c_str(), L"msedgewebview2.exe") == 0 && IsDescendantOf(pid, root, parents))
                webviews.push_back(pid);
        }
        // Avoid a duplicate mix: either capture the ordinary root tree or the
        // explicit WebView2 processes that include its AudioService.
        if (webviews.empty()) targets.push_back(root);
        else targets.insert(targets.end(), webviews.begin(), webviews.end());
    }
    return targets;
}

// The callback owns its event and result. API ownership keeps it alive after a timeout.
class Activator final : public IActivateAudioInterfaceCompletionHandler, public IAgileObject {
    std::atomic<ULONG> refs{1};
public:
    Handle done{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    ComPtr<IAudioClient> client;
    HRESULT result = E_PENDING;
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { ULONG n = --refs; if (!n) delete this; return n; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (id == __uuidof(IAgileObject)) *out = static_cast<IAgileObject*>(this);
        else if (id == __uuidof(IUnknown) || id == __uuidof(IActivateAudioInterfaceCompletionHandler))
            *out = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* op) override {
        HRESULT activation = E_FAIL; ComPtr<IUnknown> unknown;
        result = op->GetActivateResult(&activation, &unknown);
        if (SUCCEEDED(result)) result = activation;
        if (SUCCEEDED(result)) result = unknown ? unknown.As(&client) : E_NOINTERFACE;
        SetEvent(done.value); return S_OK;
    }
};
static ComPtr<IAudioClient> WaitActivation(Activator* callback, HANDLE stop, DWORD timeout) {
    HANDLE events[] = { stop, callback->done.value };
    DWORD wait = WaitForMultipleObjects(2, events, FALSE, timeout);
    if (wait == WAIT_OBJECT_0) throw std::runtime_error("Inicializacao cancelada");
    if (wait != WAIT_OBJECT_0 + 1) throw std::runtime_error("Tempo esgotado ao ativar captura de processo");
    Check(callback->result, "Ativacao de processo");
    return callback->client;
}
static ComPtr<IAudioClient> ActivateProcess(DWORD pid, HANDLE stop) {
    AUDIOCLIENT_ACTIVATION_PARAMS params{};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = pid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;
    PROPVARIANT prop{}; prop.vt = VT_BLOB; prop.blob.cbSize = sizeof(params); prop.blob.pBlobData = reinterpret_cast<BYTE*>(&params);
    ComPtr<Activator> callback; callback.Attach(new Activator());
    ComPtr<IActivateAudioInterfaceAsyncOperation> operation;
    Check(ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, __uuidof(IAudioClient), &prop, callback.Get(), &operation), "Ativar captura de processo");
    return WaitActivation(callback.Get(), stop, 8000);
}
struct Frame { float left, right; };
class Fifo {
    std::vector<Frame> frames;
    size_t read = 0, write = 0, available = 0;
    unsigned long long dropped = 0;
public:
    explicit Fifo(size_t maxFrames) : frames(maxFrames) {
        if (!maxFrames) throw std::invalid_argument("Buffer vazio");
    }
    void Push(Frame f) {
        if (available == frames.size()) {
            ++dropped;
            if (dropped == 1 || dropped % 4800 == 0)
                std::cerr << "[Buffer] frames descartados por buffer cheio: " << dropped << '\n';
            return;
        }
        frames[write] = f; write = (write + 1) % frames.size(); ++available;
    }
    Frame Pop() {
        if (!available) return {0, 0};
        Frame f = frames[read]; read = (read + 1) % frames.size(); --available; return f;
    }
    size_t Available() const { return available; }
    unsigned long long Dropped() const { return dropped; }
};
struct Stream {
    ComPtr<IAudioClient> client;
    ComPtr<IAudioCaptureClient> capture;
    ComPtr<IAudioRenderClient> render;
    UINT32 capacity = 0;
    bool started = false;
    ~Stream() { if (started) client->Stop(); }
};
static WAVEFORMATEX Format(UINT32 rate) {
    WAVEFORMATEX f{}; f.wFormatTag = WAVE_FORMAT_IEEE_FLOAT; f.nChannels = 2;
    f.nSamplesPerSec = rate; f.wBitsPerSample = 32; f.nBlockAlign = 8; f.nAvgBytesPerSec = rate * 8; return f;
}
static std::unique_ptr<Stream> OpenStream(const std::wstring& id, bool capture, UINT32 rate, DWORD pid, HANDLE stop, HANDLE audioEvent) {
    auto s = std::make_unique<Stream>();
    auto f = Format(rate);
    DWORD flags = AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
    if (pid) flags |= AUDCLNT_STREAMFLAGS_LOOPBACK;
    HRESULT initialized = E_FAIL;
    for (REFERENCE_TIME duration : {30000LL, 50000LL, 100000LL, 200000LL, 0LL}) {
        if (WaitForSingleObject(stop, 0) == WAIT_OBJECT_0) throw std::runtime_error("Inicializacao cancelada");
        // A failed Initialize can leave an audio client unusable; each retry owns a fresh one.
        s->client.Reset();
        if (pid) s->client = ActivateProcess(pid, stop);
        else {
            auto d = Device(id, capture ? eCapture : eRender);
            Check(d->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(s->client.GetAddressOf())), "Ativar dispositivo");
        }
        initialized = s->client->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, duration, 0, &f, nullptr);
        if (SUCCEEDED(initialized)) break;
    }
    Check(initialized, "Inicializar fluxo float32 stereo");
    Check(s->client->SetEventHandle(audioEvent), "Evento de audio");
    Check(s->client->GetBufferSize(&s->capacity), "Tamanho do buffer");
    if (capture) Check(s->client->GetService(IID_PPV_ARGS(&s->capture)), "Servico de captura");
    else Check(s->client->GetService(IID_PPV_ARGS(&s->render)), "Servico de reproducao");
    return s;
}
static UINT32 DeviceRate(const std::wstring& id) {
    auto d = Device(id, eRender); ComPtr<IAudioClient> c;
    Check(d->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, reinterpret_cast<void**>(c.GetAddressOf())), "Formato da saida");
    WAVEFORMATEX* f = nullptr; Check(c->GetMixFormat(&f), "Taxa da saida");
    UINT32 rate = f->nSamplesPerSec; CoTaskMemFree(f);
    if (!rate) throw std::runtime_error("Taxa de amostragem invalida");
    return rate;
}
static UINT32 Capture(Stream& s, Fifo& mix, Fifo* monitor, HANDLE stop) {
    UINT32 captured = 0;
    for (;;) {
        if (WaitForSingleObject(stop, 0) == WAIT_OBJECT_0) return captured;
        UINT32 available = 0; Check(s.capture->GetNextPacketSize(&available), "Ler estado da captura");
        if (!available) return captured;
        BYTE* data = nullptr; UINT32 count = 0; DWORD flags = 0;
        Check(s.capture->GetBuffer(&data, &count, &flags, nullptr, nullptr), "Ler captura");
        try {
            auto samples = reinterpret_cast<const float*>(data);
            for (UINT32 i = 0; i < count; ++i) {
                Frame f = (flags & AUDCLNT_BUFFERFLAGS_SILENT) ? Frame{0, 0} : Frame{samples[i * 2], samples[i * 2 + 1]};
                mix.Push(f); if (monitor) monitor->Push(f);
            }
            captured += count;
        } catch (...) { s.capture->ReleaseBuffer(count); throw; }
        Check(s.capture->ReleaseBuffer(count), "Liberar captura");
    }
}
static float SafeSample(float sample) { return std::isfinite(sample) ? std::clamp(sample, -1.0f, 1.0f) : 0.0f; }
static void Render(Stream& s, Fifo& mic, std::vector<Fifo>* processes, float micVolume, float processVolume) {
    UINT32 padding = 0; Check(s.client->GetCurrentPadding(&padding), "Estado da saida");
    if (padding > s.capacity) throw std::runtime_error("Padding de audio invalido");
    UINT32 count = s.capacity - padding; if (!count) return;
    BYTE* data = nullptr; Check(s.render->GetBuffer(count, &data), "Obter buffer de saida");
    float* samples = reinterpret_cast<float*>(data);
    for (UINT32 i = 0; i < count; ++i) {
        Frame sum = mic.Pop(); sum.left *= micVolume; sum.right *= micVolume;
        if (processes) for (Fifo& fifo : *processes) { Frame p = fifo.Pop(); sum.left += p.left * processVolume; sum.right += p.right * processVolume; }
        samples[i * 2] = SafeSample(sum.left); samples[i * 2 + 1] = SafeSample(sum.right);
    }
    Check(s.render->ReleaseBuffer(count, 0), "Enviar audio");
}
static float ParseVolume(const std::wstring& text, float scale = 1.0f) {
    size_t consumed = 0; float value = std::stof(text, &consumed) / scale;
    if (consumed != text.size() || !std::isfinite(value) || value < 0 || value > 2) throw std::runtime_error("Volume deve estar entre 0 e 200 por cento");
    return value;
}
struct Config { std::wstring mic, cable, monitor; float micVolume, processVolume; std::vector<DWORD> pids; };
class AudioEngine {
    Handle stop{CreateEventW(nullptr, TRUE, FALSE, nullptr)};
    std::thread worker;
    std::atomic<float> micVolume{1}, processVolume{1};
    void Run(Config config) {
        try {
            ComApartment apartment;
            auto captureTargets = SelectedCaptureTargets(config.pids);
            UINT32 rate = DeviceRate(config.cable);
            Handle audioEvent(CreateEventW(nullptr, FALSE, FALSE, nullptr));
            Fifo mic(rate * 2), monitor(rate * 2); std::vector<Fifo> processes;
            std::vector<std::unique_ptr<Stream>> captures;
            auto output = OpenStream(config.cable, false, rate, 0, stop.value, audioEvent.value);
            std::unique_ptr<Stream> input, headphones;
            if (config.mic != L"-1") input = OpenStream(config.mic, true, rate, 0, stop.value, audioEvent.value);
            if (config.monitor != L"-1") headphones = OpenStream(config.monitor, false, rate, 0, stop.value, audioEvent.value);
            for (DWORD pid : captureTargets) { captures.push_back(OpenStream(L"", true, rate, pid, stop.value, audioEvent.value)); processes.emplace_back(rate * 2); }
            auto start = [](Stream* s) { if (s) { Check(s->client->Start(), "Iniciar fluxo de audio"); s->started = true; } };
            start(input.get()); for (auto& s : captures) start(s.get()); start(output.get()); start(headphones.get());
            if (WaitForSingleObject(stop.value, 0) == WAIT_OBJECT_0) return;
            Protocol("READY");
            HANDLE events[] = {stop.value, audioEvent.value};
            while (true) {
                DWORD wake = WaitForMultipleObjects(2, events, FALSE, 2000);
                if (wake == WAIT_OBJECT_0) break;
                if (wake == WAIT_FAILED) throw std::runtime_error("Falha ao aguardar audio");
                if (input) Capture(*input, mic, headphones ? &monitor : nullptr, stop.value);
                for (size_t i = 0; i < captures.size(); ++i) Capture(*captures[i], processes[i], nullptr, stop.value);
                Render(*output, mic, &processes, micVolume.load(), processVolume.load());
                if (headphones) Render(*headphones, monitor, nullptr, micVolume.load(), 0);
            }
        } catch (const std::exception& error) {
            if (WaitForSingleObject(stop.value, 0) != WAIT_OBJECT_0) Protocol("ERROR\t" + Clean(error.what()));
            SetEvent(stop.value);
        } catch (...) { Protocol("ERROR\tFalha inesperada no motor de audio"); SetEvent(stop.value); }
    }
public:
    ~AudioEngine() { Stop(); }
    void Start(Config c) { micVolume = c.micVolume; processVolume = c.processVolume; worker = std::thread(&AudioEngine::Run, this, std::move(c)); }
    void Stop() { SetEvent(stop.value); if (worker.joinable()) worker.join(); }
    void Command(const std::string& raw) {
        auto first = raw.find_first_not_of(" \t\r\n"); if (first == std::string::npos) return;
        std::string line = raw.substr(first, raw.find_last_not_of(" \t\r\n") - first + 1);
        auto colon = line.find(':'); if (colon == std::string::npos) return;
        std::string key = line.substr(0, colon), value = line.substr(colon + 1);
        if (key != "mic" && key != "proc") return;
        float volume = ParseVolume(std::wstring(value.begin(), value.end()), 100);
        if (key == "mic") micVolume = volume; else processVolume = volume;
    }
};

// Binary mode used by the Python DSP host.  stdout contains only interleaved
// float32 stereo PCM; diagnostics remain on stderr so the stream is never
// corrupted by text protocol messages.
static int CaptureProcesses(UINT32 rate, const std::vector<DWORD>& selected) {
    _setmode(_fileno(stdout), _O_BINARY);
    ComApartment apartment;
    Handle stop(CreateEventW(nullptr, TRUE, FALSE, nullptr));
    Handle audioEvent(CreateEventW(nullptr, FALSE, FALSE, nullptr));
    auto roots = SelectedCaptureTargets(selected);
    std::vector<std::unique_ptr<Stream>> captures;
    std::vector<Fifo> fifos;
    for (DWORD pid : roots) {
        captures.push_back(OpenStream(L"", true, rate, pid, stop.value, audioEvent.value));
        fifos.emplace_back(rate * 2);
    }
    for (auto& stream : captures) { Check(stream->client->Start(), "Iniciar captura de processo"); stream->started = true; }
    std::vector<float> pcm;
    HANDLE events[] = {stop.value, audioEvent.value};
    while (true) {
        DWORD wake = WaitForMultipleObjects(2, events, FALSE, 2000);
        if (wake == WAIT_OBJECT_0) return 0;
        if (wake == WAIT_FAILED) throw std::runtime_error("Falha ao aguardar captura de processo");
        // Process-loopback clients signal independently.  Do not use the
        // largest packet captured in this wake: doing so pops missing frames
        // as silence from a client whose packet arrives a few milliseconds
        // later, which audibly cuts audio whenever two programs are selected.
        for (size_t i = 0; i < captures.size(); ++i)
            Capture(*captures[i], fifos[i], nullptr, stop.value);
        UINT32 frames = static_cast<UINT32>(fifos.front().Available());
        for (size_t i = 1; i < fifos.size(); ++i)
            frames = std::min(frames, static_cast<UINT32>(fifos[i].Available()));
        if (!frames) continue;
        pcm.resize(static_cast<size_t>(frames) * 2);
        for (UINT32 frame = 0; frame < frames; ++frame) {
            Frame sum{0, 0};
            for (Fifo& fifo : fifos) { Frame item = fifo.Pop(); sum.left += item.left; sum.right += item.right; }
            pcm[frame * 2] = SafeSample(sum.left); pcm[frame * 2 + 1] = SafeSample(sum.right);
        }
        std::cout.write(reinterpret_cast<const char*>(pcm.data()), static_cast<std::streamsize>(pcm.size() * sizeof(float)));
        std::cout.flush();
        if (!std::cout) return 0; // Parent closed the pipe.
    }
}
#ifndef PLACASOM_TEST
int wmain(int argc, wchar_t* argv[]) {
    try {
        if (argc == 2 && std::wstring(argv[1]) == L"--list") { ComApartment apartment; ListDevices(); return 0; }
        if (argc >= 4 && std::wstring(argv[1]) == L"--capture") {
            size_t consumed = 0; UINT32 rate = static_cast<UINT32>(std::stoul(argv[2], &consumed));
            if (!rate || consumed != std::wstring(argv[2]).size()) throw std::runtime_error("Taxa de captura invalida");
            std::vector<DWORD> pids;
            for (int i = 3; i < argc; ++i) {
                std::wstring value(argv[i]); size_t used = 0; unsigned long pid = std::stoul(value, &used);
                if (!pid || used != value.size()) throw std::runtime_error("PID invalido");
                pids.push_back(static_cast<DWORD>(pid));
            }
            return CaptureProcesses(rate, pids);
        }
        if (argc < 7 || std::wstring(argv[1]) != L"--run") throw std::runtime_error("Uso: Placasom.exe --run <micId|-1> <cableId> <returnId|-1> <volMic> <volProc> [PIDs...]");
        Config c{argv[2], argv[3], argv[4], ParseVolume(argv[5]), ParseVolume(argv[6]), {}};
        if (c.cable == L"-1" || c.cable.empty()) throw std::runtime_error("Selecione uma saida virtual");
        if (c.cable == c.monitor) throw std::runtime_error("Retorno e saida virtual devem ser diferentes");
        for (int i = 7; i < argc; ++i) {
            std::wstring value(argv[i]); size_t consumed = 0;
            if (value.empty() || value.find_first_not_of(L"0123456789") != std::wstring::npos) throw std::runtime_error("PID invalido");
            unsigned long pid = std::stoul(value, &consumed);
            if (!pid || consumed != value.size()) throw std::runtime_error("PID invalido"); c.pids.push_back(pid);
        }
        AudioEngine engine; engine.Start(std::move(c));
        std::string line;
        while (std::getline(std::cin, line)) {
            auto first = line.find_first_not_of(" \t\r\n"); if (first == std::string::npos) continue;
            std::string command = line.substr(first, line.find_last_not_of(" \t\r\n") - first + 1);
            if (command == "stop" || command == "exit" || command == "quit") break;
            engine.Command(command);
        }
        engine.Stop(); return 0;
    } catch (const std::exception& error) {
        if (argc >= 2 && std::wstring(argv[1]) == L"--capture")
            std::cerr << Clean(error.what()) << std::endl;
        else Protocol("ERROR\t" + Clean(error.what()));
        return 1;
    }
}
#endif
