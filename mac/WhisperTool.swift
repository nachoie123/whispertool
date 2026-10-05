// WhisperTool para Mac: app de barra de menús, sin ventana ni icono en el Dock.
// Mantén ⌃⌥ para dictar → Whisper en Groq (large-v3-turbo) → pulido con IA → se pega donde está el cursor.
// La versión Python (main.py) cargaba Whisper en la GPU todo el día: 2,6 GB de memoria aunque no dictaras.
// Esta no carga ningún modelo: en reposo no hay micro, ni temporizadores, ni audio abierto.
import AppKit
import SwiftUI
import AVFoundation
import Speech
import ServiceManagement
import ApplicationServices

// Datos en Application Support; si existe la carpeta de la versión Python (~/whispertool/config.json), se sigue usando esa
let carpeta: URL = {
    let fm = FileManager.default
    let vieja = fm.homeDirectoryForCurrentUser.appendingPathComponent("whispertool")
    if fm.fileExists(atPath: vieja.appendingPathComponent("config.json").path) { return vieja }
    let nueva = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("WhisperTool")
    try? fm.createDirectory(at: nueva, withIntermediateDirectories: true)
    return nueva
}()
let rutaConfig = carpeta.appendingPathComponent("config.json")
let rutaHistorial = carpeta.appendingPathComponent("history.json")
let rutaUltimoAudio = carpeta.appendingPathComponent("ultimo.wav")   // por si falla: «Reintentar el último audio»


let promptBase = """
Rewrite the following text to make it clear, well-structured, and free of any grammatical or language errors. \
Preserve the original meaning and intent. Spoken punctuation commands ("coma", "punto", "nueva línea", "comma", "period", "new line") \
become the actual punctuation. If the speaker enumerates items, format them as a numbered list. \
Only return the rewritten text, nothing else.
"""

let estiloEmail = """
Format this as a well-structured email, in the SAME language as the text. Start with an appropriate greeting line \
(e.g. 'Hola,' or 'Hi,') followed by a blank line; organize the body into short paragraphs separated by blank lines; \
end with a short closing line (e.g. 'Un saludo,' / 'Best,'). Do NOT invent facts, names, recipients, or content that \
were not dictated — only structure and lightly clean what is there. Keep it concise and natural, never flowery. \
Return only the email text.
"""

// «estoy escribiendo un email, …» / «correo: …» al principio → formato de correo (igual que main.py)
let disparadorEmail: NSRegularExpression = {
    let kw = #"(?:e-?mails?|correos?(?:\s+electr[oó]nicos?)?|mails?)"#
    let frase = #"(?:esto|este)\s+es\s+(?:un\s+)?|estoy\s+escribiendo\s+(?:un\s+)?|escr[ií]b(?:e|o|iendo)(?:me)?\s+(?:un\s+)?|redacta(?:me)?\s+(?:un\s+)?|haz(?:me)?\s+(?:un\s+)?|(?:en\s+)?formato\s+(?:de\s+)?|modo\s+|this\s+is\s+an?\s+|i'?m\s+writing\s+an?\s+|write\s+(?:me\s+)?an?\s+|format\s+as\s+an?\s+"#
    let p = #"^\s*(?:(?:"# + frase + ")" + kw + #"[\s,.:;¡!¿?-]*|"# + kw + #"\s*[,.:;-]+\s*)"#
    return try! NSRegularExpression(pattern: p, options: [.caseInsensitive])
}()

func detectarEmail(_ t: String) -> (Bool, String) {
    let ns = t as NSString
    guard let m = disparadorEmail.firstMatch(in: t, range: NSRange(location: 0, length: ns.length)) else { return (false, t) }
    let resto = ns.substring(from: m.range.upperBound).trimmingCharacters(in: .whitespaces)
    return resto.isEmpty ? (false, t) : (true, resto)
}

// Lo que Whisper «oye» en el silencio. Solo se descarta si el dictado de Apple tampoco oyó nada.
let alucinaciones = ["gracias.", "gracias por ver el video.", "¡gracias por ver!", "subtítulos realizados por la comunidad de amara.org",
                     "thank you.", "thanks for watching!", "you", "¡suscríbete!", "..."]

// MARK: - Ajustes (los mismos de config.json que usaba main.py)

@MainActor
final class Ajustes: ObservableObject {
    static let shared = Ajustes()
    @Published var pulir = true { didSet { guardar() } }
    @Published var clave = "" { didSet { guardar() } }
    @Published var estilo = "" { didSet { guardar() } }
    @Published var textoEnVivo = true { didSet { guardar() } }
    // Pistas de vocabulario para Whisper: nombres propios que dices a menudo (sin ellas «Nacho» salía «NATO»)
    @Published var vocabulario = "" { didSet { guardar() } }
    private var cargando = true

    init() {
        let d = leer()
        pulir = d["ai_rewrite"] as? Bool ?? true
        clave = (d["ai_api_keys"] as? [String: Any])?["Groq"] as? String ?? ""
        estilo = d["ai_style"] as? String ?? ""
        textoEnVivo = d["live_text"] as? Bool ?? true
        vocabulario = d["whisper_prompt"] as? String ?? ""
        cargando = false
    }

    private func leer() -> [String: Any] {
        guard let data = try? Data(contentsOf: rutaConfig),
              let d = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return d
    }

    private func guardar() {
        guard !cargando else { return }
        var d = leer()                                   // conserva las claves que no toca esta app
        d["ai_rewrite"] = pulir
        d["ai_provider"] = "Groq"
        var claves = d["ai_api_keys"] as? [String: Any] ?? [:]
        claves["Groq"] = clave
        d["ai_api_keys"] = claves
        d["ai_style"] = estilo
        d["live_text"] = textoEnVivo
        d["whisper_prompt"] = vocabulario
        if let data = try? JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: rutaConfig, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: rutaConfig.path)  // lleva claves
        }
    }
}

struct Dictado: Codable, Identifiable, Hashable {
    var id = UUID()
    var texto: String
    var fecha: Date
}

@MainActor
final class Historial: ObservableObject {
    static let shared = Historial()
    @Published var items: [Dictado] = []
    @Published var audioPendiente = false            // el último audio no se pudo transcribir

    init() {
        if let d = try? Data(contentsOf: rutaHistorial), let v = try? JSONDecoder().decode([Dictado].self, from: d) { items = v }
    }

    func añadir(_ t: String) {
        items.insert(Dictado(texto: t, fecha: Date()), at: 0)
        if items.count > 50 { items.removeLast(items.count - 50) }
        if let d = try? JSONEncoder().encode(items) { try? d.write(to: rutaHistorial, options: .atomic) }
    }
}

// MARK: - Groq (Whisper + pulido)

enum Groq {
    static func peticion(_ ruta: String, _ clave: String, espera: TimeInterval) -> URLRequest {
        var r = URLRequest(url: URL(string: "https://api.groq.com/openai/v1/" + ruta)!, timeoutInterval: espera)
        r.httpMethod = "POST"
        r.setValue("Bearer \(clave)", forHTTPHeaderField: "Authorization")
        r.setValue("WhisperTool/2.0", forHTTPHeaderField: "User-Agent")   // el UA por defecto da 403 en su Cloudflare
        return r
    }

    static func transcribir(_ wav: Data, clave: String, pista: String) async throws -> String {
        let b = "----wt\(UUID().uuidString)"
        var r = peticion("audio/transcriptions", clave, espera: 15)
        r.setValue("multipart/form-data; boundary=\(b)", forHTTPHeaderField: "Content-Type")
        var cuerpo = Data()
        func campo(_ n: String, _ v: String) { cuerpo.append("--\(b)\r\nContent-Disposition: form-data; name=\"\(n)\"\r\n\r\n\(v)\r\n".data(using: .utf8)!) }
        campo("model", "whisper-large-v3-turbo")
        campo("temperature", "0")
        campo("response_format", "json")
        if !pista.isEmpty { campo("prompt", pista) }
        cuerpo.append("--\(b)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.wav\"\r\nContent-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        cuerpo.append(wav)
        cuerpo.append("\r\n--\(b)--\r\n".data(using: .utf8)!)
        r.httpBody = cuerpo
        let (d, resp) = try await URLSession.shared.data(for: r)
        guard (resp as? HTTPURLResponse)?.statusCode == 200,
              let j = try JSONSerialization.jsonObject(with: d) as? [String: Any], let t = j["text"] as? String else {
            throw NSError(domain: "Groq", code: (resp as? HTTPURLResponse)?.statusCode ?? 0,
                          userInfo: [NSLocalizedDescriptionKey: String(data: d.prefix(200), encoding: .utf8) ?? ""])
        }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func pulir(_ t: String, estilo: String, clave: String) async throws -> String {
        var sistema = promptBase
        if !estilo.trimmingCharacters(in: .whitespaces).isEmpty { sistema += "\n\nAdditional style and tone instructions: \(estilo)" }
        var r = peticion("chat/completions", clave, espera: 4)
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": "qwen/qwen3.8-27b",
            "messages": [["role": "system", "content": sistema], ["role": "user", "content": "Text to rewrite:\n\(t)"]],
        ])
        let (d, resp) = try await URLSession.shared.data(for: r)
        guard (resp as? HTTPURLResponse)?.statusCode == 200,
              let j = try JSONSerialization.jsonObject(with: d) as? [String: Any],
              let c = ((j["choices"] as? [[String: Any]])?.first?["message"] as? [String: Any])?["content"] as? String else {
            throw NSError(domain: "Groq", code: 1)
        }
        // por si el modelo piensa en voz alta
        let limpio = c.replacingOccurrences(of: #"(?s)<think>.*?</think>"#, with: "", options: .regularExpression)
        return limpio.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - Grabación (hilo de audio → muestras en memoria)

final class Grabacion: @unchecked Sendable {
    private let lock = NSLock()
    private var muestras: [Float] = []
    private var ritmo = 48000.0
    private(set) var pico: Float = 0                  // RMS más alto de un bloque: distingue voz de silencio

    func empezar(ritmo r: Double) { lock.lock(); muestras.removeAll(keepingCapacity: true); ritmo = r; pico = 0; lock.unlock() }

    func meter(_ b: AVAudioPCMBuffer) -> Float {
        guard let d = b.floatChannelData?[0] else { return 0 }
        let n = Int(b.frameLength)
        var s: Float = 0
        for i in 0..<n { s += d[i] * d[i] }
        let rms = sqrt(s / Float(max(1, n)))
        lock.lock()
        if Double(muestras.count) < ritmo * 600 { muestras.append(contentsOf: UnsafeBufferPointer(start: d, count: n)) }  // tope 10 min
        pico = max(pico, rms)
        lock.unlock()
        return rms
    }

    /// WAV mono 16 kHz de 16 bits: 1/6 de lo que pesa el float de 48 kHz, así sube a Groq en nada.
    func wav16k() -> (Data, Double) {
        lock.lock(); let m = muestras, r = ritmo; lock.unlock()
        let paso = r / 16000, n = Int(Double(m.count) / paso)
        var pcm = [Int16](repeating: 0, count: n)
        for i in 0..<n {                                   // media de cada tramo = filtro antialias simple
            let a = Int(Double(i) * paso), b = max(a + 1, min(m.count, Int(Double(i + 1) * paso)))
            var s: Float = 0
            for k in a..<b { s += m[k] }
            pcm[i] = Int16(max(-1, min(1, s / Float(b - a))) * 32767)
        }
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        d.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + n * 2)); d.append("WAVEfmt ".data(using: .ascii)!)
        u32(16); u16(1); u16(1); u32(16000); u32(32000); u16(2); u16(16)
        d.append("data".data(using: .ascii)!); u32(UInt32(n * 2))
        pcm.withUnsafeBytes { d.append(contentsOf: $0) }
        return (d, Double(m.count) / r)
    }
}

// MARK: - Isla (la píldora negra que sale del notch)

enum Fase { case escuchando, transcribiendo, hecho, error }

@MainActor
final class IslaModelo: ObservableObject {
    @Published var visible = false
    @Published var fase = Fase.escuchando
    @Published var texto = ""
    @Published var barras: [CGFloat] = Array(repeating: 0.15, count: 5)
}

struct Ondas: View {
    let barras: [CGFloat]
    let fase: Fase
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: fase != .transcribiendo)) { tl in
            let t = tl.date.timeIntervalSinceReferenceDate
            HStack(spacing: 3) {
                ForEach(0..<5, id: \.self) { i in
                    let h: CGFloat = fase == .transcribiendo
                        ? 0.25 + 0.3 * CGFloat((sin(t * 7 - Double(i) * 0.8) + 1) / 2)   // ola suave mientras piensa
                        : barras[i]
                    Capsule()
                        .fill(i == 2 ? AnyShapeStyle(LinearGradient(colors: [Color(red: 1, green: 0.42, blue: 0.24), Color(red: 1, green: 0.7, blue: 0.2)],
                                                                    startPoint: .bottom, endPoint: .top))
                                     : AnyShapeStyle(Color.white.opacity(fase == .transcribiendo ? 0.55 : 0.92)))
                        .frame(width: 3.5, height: max(4, 22 * h))
                }
            }
            .frame(width: 30, height: 22)
            .animation(.spring(response: 0.16, dampingFraction: 0.75), value: barras)
        }
    }
}

struct IslaVista: View {
    @ObservedObject var m: IslaModelo
    let notch: Bool

    var mensaje: String {
        if !m.texto.isEmpty { return m.texto }
        switch m.fase {
        case .escuchando: return "Escuchando…"
        case .transcribiendo: return "Transcribiendo…"
        case .hecho: return "Hecho"
        case .error: return "No te he oído"
        }
    }

    var body: some View {
        let forma = UnevenRoundedRectangle(topLeadingRadius: notch ? 0 : 20, bottomLeadingRadius: 20,
                                           bottomTrailingRadius: 20, topTrailingRadius: notch ? 0 : 20, style: .continuous)
        HStack(alignment: .center, spacing: 12) {
            Group {
                switch m.fase {
                case .hecho: Image(systemName: "checkmark.circle.fill").foregroundStyle(Color(red: 0.3, green: 0.85, blue: 0.5))
                case .error: Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Color(red: 1, green: 0.72, blue: 0.2))
                default: Ondas(barras: m.barras, fase: m.fase)
                }
            }
            .font(.system(size: 18, weight: .semibold))
            .frame(width: 30, height: 22)
            .transition(.scale.combined(with: .opacity))

            Text(mensaje)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(m.texto.isEmpty ? Color.white.opacity(0.55) : Color.white)
                .lineLimit(2)
                .truncationMode(.head)                    // con mucho texto se ve el final: lo que acabas de decir
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentTransition(.opacity)
                .animation(.easeOut(duration: 0.12), value: m.texto)
        }
        .padding(.horizontal, 18)
        .padding(.top, notch ? 38 : 12)                   // con notch: el texto empieza por debajo de él
        .padding(.bottom, 12)
        .frame(width: 440)
        .background(forma.fill(Color.black))
        .overlay(forma.strokeBorder(Color.white.opacity(notch ? 0 : 0.08), lineWidth: 1))
        .shadow(color: .black.opacity(0.35), radius: 18, y: 8)
        .scaleEffect(m.visible ? 1 : 0.55, anchor: .top)
        .opacity(m.visible ? 1 : 0)
        .animation(.spring(response: 0.38, dampingFraction: 0.82), value: m.visible)
        .animation(.spring(response: 0.3, dampingFraction: 0.9), value: m.fase)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
}

@MainActor
final class Isla {
    static let shared = Isla()
    let m = IslaModelo()
    private var panel: NSPanel?
    private var ocultarTrabajo: DispatchWorkItem?

    func mostrar() {
        ocultarTrabajo?.cancel()
        // la pantalla donde está el ratón (donde estás escribiendo)
        let raton = NSEvent.mouseLocation
        let pantalla = NSScreen.screens.first { NSMouseInRect(raton, $0.frame, false) } ?? NSScreen.main!
        let notch = pantalla.safeAreaInsets.top > 0
        let w: CGFloat = 520, h: CGFloat = 160
        let f = pantalla.frame
        let y = notch ? f.maxY - h : pantalla.visibleFrame.maxY - h - 8
        let marco = NSRect(x: f.midX - w / 2, y: y, width: w, height: h)
        if panel == nil || panel!.screen != pantalla {
            panel?.orderOut(nil)
            let p = NSPanel(contentRect: marco, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
            p.isOpaque = false
            p.backgroundColor = .clear
            p.hasShadow = false
            p.level = .popUpMenu                           // por encima de la barra de menús y de apps a pantalla completa
            p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
            p.ignoresMouseEvents = true
            p.contentView = NSHostingView(rootView: IslaVista(m: m, notch: notch))
            panel = p
        }
        panel!.setFrame(marco, display: false)
        panel!.orderFrontRegardless()
        m.visible = true
    }

    func ocultar(tras: Double = 0) {
        ocultarTrabajo?.cancel()
        let t = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.m.visible = false
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                // destruir, no esconder: una vista SwiftUI escondida seguía refrescando la pantalla (~10 % de CPU en reposo)
                if !self.m.visible { self.panel?.orderOut(nil); self.panel = nil; self.m.texto = "" }
            }
        }
        ocultarTrabajo = t
        DispatchQueue.main.asyncAfter(deadline: .now() + tras, execute: t)
    }
}

// MARK: - Dictado

/// Un dictado: su petición a Apple y lo que va oyendo. Cada uno la suya, así uno nuevo no pisa al que aún se transcribe.
@MainActor
final class Sesion {
    var peticion: SFSpeechAudioBufferRecognitionRequest?
    var tarea: SFSpeechRecognitionTask?
    var vivo = ""
}

@MainActor
final class Dictador {
    static let shared = Dictador()
    private var motor: AVAudioEngine?
    private let grab = Grabacion()
    private var sesion: Sesion?
    private let reconocedor = SFSpeechRecognizer()                // idioma del sistema
    private(set) var grabando = false
    private var tInicio = Date()
    private var tNivel = 0.0

    /// Pitido con afplay (proceso aparte que acaba y suelta el altavoz). NSSound dejaba la salida de audio
    /// abierta para siempre: ~1.000 despertares por segundo con la app en reposo.
    private func pitido(_ nombre: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/afplay")
        p.arguments = [Bundle.main.url(forResource: nombre, withExtension: nil)?.path ?? ""]
        try? p.run()
    }

    var segundos: Double { Date().timeIntervalSince(tInicio) }

    func empezar() {
        guard !grabando else { return }
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
            avisar("Falta permiso de micrófono")
            return
        }
        // Un motor nuevo cada vez: si cambias de micro (AirPods…) el formato viejo rompía la grabación
        let m = AVAudioEngine()
        let entrada = m.inputNode
        let formato = entrada.outputFormat(forBus: 0)
        guard formato.sampleRate > 0, formato.channelCount > 0 else { avisar("No encuentro el micrófono"); return }
        grab.empezar(ritmo: formato.sampleRate)
        let ses = Sesion()
        sesion = ses
        let isla = Isla.shared.m
        isla.texto = ""; isla.fase = .escuchando; isla.barras = Array(repeating: 0.15, count: 5)

        var p: SFSpeechAudioBufferRecognitionRequest?
        if Ajustes.shared.textoEnVivo, SFSpeechRecognizer.authorizationStatus() == .authorized, let r = reconocedor, r.isAvailable {
            let pr = SFSpeechAudioBufferRecognitionRequest()
            pr.shouldReportPartialResults = true
            if r.supportsOnDeviceRecognition { pr.requiresOnDeviceRecognition = true }   // en el Mac, sin red
            pr.taskHint = .dictation
            pr.contextualStrings = Ajustes.shared.vocabulario.components(separatedBy: CharacterSet(charactersIn: ".,;\n"))
                .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            ses.tarea = r.recognitionTask(with: pr) { res, _ in
                guard let res else { return }
                let t = res.bestTranscription.formattedString
                DispatchQueue.main.async { MainActor.assumeIsolated {
                    ses.vivo = t
                    if self.sesion === ses && self.grabando { Isla.shared.m.texto = t }
                } }
            }
            ses.peticion = pr
            p = pr
        }
        let g = grab
        entrada.installTap(onBus: 0, bufferSize: 1024, format: formato) { buf, _ in
            p?.append(buf)
            let rms = g.meter(buf)
            DispatchQueue.main.async { MainActor.assumeIsolated { Dictador.shared.nivel(rms) } }
        }
        do { m.prepare(); try m.start() } catch {
            entrada.removeTap(onBus: 0)
            avisar("No puedo abrir el micrófono")
            return
        }
        motor = m
        grabando = true
        tInicio = Date()
        pitido("beep_start.wav")          // suena cuando YA graba: es tu señal para hablar
        Barra.shared.grabando(true)
        Isla.shared.mostrar()
    }

    private func nivel(_ rms: Float) {
        guard grabando else { return }
        let ahora = CACurrentMediaTime()
        guard ahora - tNivel > 1.0 / 20 else { return }     // 20 veces/s basta para el ojo
        tNivel = ahora
        let v = CGFloat(min(1, sqrt(rms / 0.12)))
        var b = Isla.shared.m.barras
        b.removeFirst(); b.append(max(0.15, v))
        Isla.shared.m.barras = b.enumerated().map { i, x in max(0.15, x * [0.65, 0.85, 1, 0.85, 0.65][i]) }
    }

    func terminar(cancelar: Bool = false) {
        guard grabando, let m = motor else { return }
        grabando = false
        motor = nil
        m.inputNode.removeTap(onBus: 0)
        // CoreAudio puede tardar en soltar el micro: que espere un hilo aparte, nunca la app (main.py se colgaba ahí)
        DispatchQueue.global(qos: .userInitiated).async { m.stop() }
        let ses = sesion!
        ses.peticion?.endAudio()
        Barra.shared.grabando(false)
        pitido("beep_stop.wav")
        let dur = segundos
        if cancelar || dur < 0.35 {
            ses.tarea?.cancel()
            Isla.shared.ocultar()
            return
        }
        let (wav, _) = grab.wav16k()
        let pico = grab.pico
        try? wav.write(to: rutaUltimoAudio, options: .atomic)
        Isla.shared.m.fase = .transcribiendo
        Task { await procesar(wav: wav, pico: pico, ses: ses) }
    }

    func reintentarUltimo() {
        guard let wav = try? Data(contentsOf: rutaUltimoAudio) else { return }
        Isla.shared.m.texto = ""; Isla.shared.m.fase = .transcribiendo
        Isla.shared.mostrar()
        Task { await procesar(wav: wav, pico: 1, ses: Sesion()) }
    }

    private func procesar(wav: Data, pico: Float, ses: Sesion) async {
        defer { ses.tarea?.cancel() }
        let vivo = ses.vivo
        let a = Ajustes.shared
        // Silencio de verdad (y Apple tampoco oyó nada): no molestes a Whisper, que se inventa «Gracias.»
        if pico < 0.006 && vivo.isEmpty { fallo("No te he oído", guardado: false); return }

        var texto = ""
        if !a.clave.isEmpty {
            for intento in 0..<2 where texto.isEmpty {
                do { texto = try await Groq.transcribir(wav, clave: a.clave, pista: a.vocabulario) }
                catch { print("[!] Whisper intento \(intento + 1): \(error.localizedDescription)") }
            }
        }
        if vivo.isEmpty && alucinaciones.contains(texto.lowercased()) { texto = "" }
        // Groq caído o sin red: vale lo que oyó el dictado de Apple en el Mac. Nunca se pierde.
        if texto.isEmpty { texto = ses.vivo }            // ya con el resultado final de Apple, si llegó
        guard !texto.isEmpty else { fallo("No he podido transcribir. Audio guardado: menú → Reintentar", guardado: true); return }
        Historial.shared.audioPendiente = false

        let (email, cuerpo) = detectarEmail(texto)
        var final = cuerpo
        Isla.shared.m.texto = cuerpo
        if a.pulir, !a.clave.isEmpty {
            if let p = try? await Groq.pulir(cuerpo, estilo: email ? estiloEmail : a.estilo, clave: a.clave), !p.isEmpty { final = p }
        }
        await pegar(final)
        Historial.shared.añadir(final)
        Isla.shared.m.texto = final
        Isla.shared.m.fase = .hecho
        Isla.shared.ocultar(tras: 1.2)
    }

    private func fallo(_ msg: String, guardado: Bool) {
        if guardado { Historial.shared.audioPendiente = true }
        Isla.shared.m.texto = msg
        Isla.shared.m.fase = .error
        Isla.shared.ocultar(tras: guardado ? 3 : 1.2)
    }

    private func avisar(_ msg: String) {
        Isla.shared.m.texto = msg
        Isla.shared.m.fase = .error
        Isla.shared.mostrar()
        Isla.shared.ocultar(tras: 2.5)
    }

    /// Pega con ⌘V donde esté el cursor y luego devuelve lo que tenías en el portapapeles.
    private func pegar(_ t: String) async {
        // Si aún tienes ⌃ o ⌥ pulsada, ⌘V se convertiría en ⌃⌘V y no pegaría nada: espera a que sueltes (máx. 0,6 s)
        for _ in 0..<30 where !NSEvent.modifierFlags.intersection([.control, .option, .command]).isEmpty {
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        let pb = NSPasteboard.general
        let guardado: [[NSPasteboard.PasteboardType: Data]] = (pb.pasteboardItems ?? []).map { item in
            var d: [NSPasteboard.PasteboardType: Data] = [:]
            for tipo in item.types { if let v = item.data(forType: tipo) { d[tipo] = v } }
            return d
        }
        pb.clearContents()
        pb.setString(t, forType: .string)
        let cuenta = pb.changeCount
        let src = CGEventSource(stateID: .combinedSessionState)
        for abajo in [true, false] {
            let e = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: abajo)   // 9 = V
            e?.flags = .maskCommand                                                     // solo ⌘, pase lo que pase con el teclado
            e?.post(tap: .cghidEventTap)
        }
        try? await Task.sleep(nanoseconds: 600_000_000)
        guard pb.changeCount == cuenta, !guardado.isEmpty else { return }    // si copiaste algo entretanto, no lo piso
        pb.clearContents()
        pb.writeObjects(guardado.map { d in
            let it = NSPasteboardItem()
            for (tipo, v) in d { it.setData(v, forType: tipo) }
            return it
        })
    }
}

// MARK: - Atajo: mantener ⌃⌥

@MainActor
enum Atajo {
    static func instalar() {
        NSEvent.addGlobalMonitorForEvents(matching: [.flagsChanged, .keyDown]) { e in MainActor.assumeIsolated { manejar(e) } }
        NSEvent.addLocalMonitorForEvents(matching: [.flagsChanged, .keyDown]) { e in MainActor.assumeIsolated { manejar(e) }; return e }
    }

    static func manejar(_ e: NSEvent) {
        let d = Dictador.shared
        if e.type == .keyDown {
            // ⌃⌥ + otra tecla en el primer instante = era un atajo de otra app, no un dictado
            if d.grabando && d.segundos < 0.4 { d.terminar(cancelar: true) }
            return
        }
        let f = e.modifierFlags.intersection(.deviceIndependentFlagsMask)
        let ambas = f.contains(.control) && f.contains(.option) && !f.contains(.command)
        if ambas && !d.grabando { d.empezar() }
        else if !ambas && d.grabando { d.terminar() }
    }
}

// MARK: - Barra de menús

@MainActor
final class Barra: NSObject, NSMenuDelegate {
    static let shared = Barra()
    private var item: NSStatusItem!
    private var ventana: NSWindow?

    func instalar() {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        grabando(false)
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
    }

    func grabando(_ si: Bool) {
        let img = NSImage(systemSymbolName: si ? "waveform.circle.fill" : "waveform", accessibilityDescription: "WhisperTool")
        img?.isTemplate = true
        item?.button?.image = img
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let cab = NSMenuItem(title: "Mantén ⌃⌥ para dictar", action: nil, keyEquivalent: "")
        cab.isEnabled = false
        menu.addItem(cab)
        if !AXIsProcessTrusted() {
            menu.addItem(accion("⚠︎ Activa WhisperTool en Accesibilidad…", #selector(abrirAccesibilidad)))
        }
        menu.addItem(.separator())

        let recientes = NSMenuItem(title: "Recientes", action: nil, keyEquivalent: "")
        let sub = NSMenu()
        for d in Historial.shared.items.prefix(10) {
            let t = d.texto.replacingOccurrences(of: "\n", with: " ")
            let it = accion(t.count > 60 ? String(t.prefix(60)) + "…" : t, #selector(copiar(_:)))
            it.representedObject = d.texto
            it.toolTip = "Clic para copiar"
            sub.addItem(it)
        }
        if sub.items.isEmpty { let v = NSMenuItem(title: "Aún nada", action: nil, keyEquivalent: ""); v.isEnabled = false; sub.addItem(v) }
        recientes.submenu = sub
        menu.addItem(recientes)
        if Historial.shared.audioPendiente { menu.addItem(accion("Reintentar el último audio", #selector(reintentar))) }
        menu.addItem(.separator())

        let a = Ajustes.shared
        menu.addItem(interruptor("Pulir con IA", a.pulir, #selector(cambiarPulir)))
        menu.addItem(interruptor("Texto en vivo", a.textoEnVivo, #selector(cambiarVivo)))
        menu.addItem(interruptor("Abrir al iniciar sesión", SMAppService.mainApp.status == .enabled, #selector(cambiarInicio)))
        menu.addItem(.separator())
        let aj = accion("Ajustes…", #selector(abrirAjustes))
        aj.keyEquivalent = ","
        menu.addItem(aj)
        menu.addItem(accion("Salir de WhisperTool", #selector(salir)))
    }

    private func accion(_ t: String, _ s: Selector) -> NSMenuItem {
        let i = NSMenuItem(title: t, action: s, keyEquivalent: "")
        i.target = self
        return i
    }

    private func interruptor(_ t: String, _ on: Bool, _ s: Selector) -> NSMenuItem {
        let i = accion(t, s)
        i.state = on ? .on : .off
        return i
    }

    @objc func copiar(_ s: NSMenuItem) {
        guard let t = s.representedObject as? String else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(t, forType: .string)
    }
    @objc func reintentar() { Dictador.shared.reintentarUltimo() }
    @objc func cambiarPulir() { Ajustes.shared.pulir.toggle() }
    @objc func cambiarVivo() { Ajustes.shared.textoEnVivo.toggle() }
    @objc func cambiarInicio() { Inicio.cambiar(SMAppService.mainApp.status != .enabled) }
    @objc func abrirAccesibilidad() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }
    @objc func salir() { NSApp.terminate(nil) }

    @objc func abrirAjustes() {
        if ventana == nil {
            let w = NSWindow(contentViewController: NSHostingController(rootView: AjustesVista()))
            w.title = "WhisperTool"
            w.styleMask = [.titled, .closable, .fullSizeContentView]
            w.titlebarAppearsTransparent = true
            w.isReleasedWhenClosed = false
            w.center()
            ventana = w
        }
        NSApp.activate(ignoringOtherApps: true)
        ventana?.makeKeyAndOrderFront(nil)
    }
}

enum Inicio {
    static func cambiar(_ on: Bool) {
        do { if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() } }
        catch { print("[!] inicio de sesión: \(error)") }
    }
}

// MARK: - Ventana de ajustes

struct AjustesVista: View {
    @ObservedObject var a = Ajustes.shared
    @ObservedObject var h = Historial.shared
    @State var inicio = SMAppService.mainApp.status == .enabled
    @State var mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    @State var voz = SFSpeechRecognizer.authorizationStatus() == .authorized
    @State var acc = AXIsProcessTrusted()

    var body: some View {
        Form {
            Section {
                HStack(spacing: 14) {
                    Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 48, height: 48)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("WhisperTool").font(.title2.weight(.semibold))
                        Text("Mantén \(Text("⌃ Control + ⌥ Opción").fontWeight(.semibold)) y habla. Al soltar, el texto se pega donde está el cursor.")
                            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.vertical, 4)
            }
            Section("Pulido con IA") {
                Toggle("Limpiar muletillas, repeticiones y puntuación", isOn: $a.pulir)
                SecureField("Clave de Groq", text: $a.clave, prompt: Text("gsk_…  (gratis en console.groq.com)"))
                TextField("Vocabulario", text: $a.vocabulario, prompt: Text("Nombres que dices a menudo: Ana, IE University…"))
                VStack(alignment: .leading, spacing: 6) {
                    Text("Instrucciones de estilo").font(.callout).foregroundStyle(.secondary)
                    TextEditor(text: $a.estilo)
                        .font(.callout)
                        .frame(height: 74)
                        .scrollContentBackground(.hidden)
                        .padding(6)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.05)))
                }
            }
            Section("General") {
                Toggle("Ver el texto en vivo mientras hablas", isOn: $a.textoEnVivo)
                Toggle("Abrir al iniciar sesión", isOn: $inicio)
                    .onChange(of: inicio) { _, v in Inicio.cambiar(v) }
            }
            Section("Permisos") {
                permiso("Micrófono", mic, "Privacy_Microphone")
                permiso("Reconocimiento de voz (texto en vivo)", voz, "Privacy_SpeechRecognition")
                permiso("Accesibilidad (atajo y pegar)", acc, "Privacy_Accessibility")
            }
            if !h.items.isEmpty {
                Section("Recientes") {
                    ForEach(h.items.prefix(8)) { d in
                        HStack(alignment: .top) {
                            Text(d.texto).lineLimit(2).font(.callout)
                            Spacer()
                            Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(d.texto, forType: .string) }
                                label: { Image(systemName: "doc.on.doc") }
                                .buttonStyle(.borderless).help("Copiar")
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 480, height: 620)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
            voz = SFSpeechRecognizer.authorizationStatus() == .authorized
            acc = AXIsProcessTrusted()
        }
    }

    func permiso(_ nombre: String, _ ok: Bool, _ panel: String) -> some View {
        HStack {
            Text(nombre)
            Spacer()
            if ok { Label("Activado", systemImage: "checkmark.circle.fill").foregroundStyle(.green).labelStyle(.titleAndIcon) }
            else {
                Button("Activar…") {
                    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?\(panel)")!)
                }
            }
        }
    }
}

// MARK: - Arranque

@main
struct WhisperToolApp {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let d = Delegado()
        app.delegate = d
        app.run()
    }
}

final class Delegado: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ n: Notification) {
        MainActor.assumeIsolated {
            Barra.shared.instalar()
            Atajo.instalar()
            AVCaptureDevice.requestAccess(for: .audio) { _ in }
            SFSpeechRecognizer.requestAuthorization { _ in }
            // Pide Accesibilidad (sin ella no hay atajo global ni ⌘V)
            let op = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(op)
            // primera vez: que arranque solo al iniciar sesión, como Macs Fan Control
            if !UserDefaults.standard.bool(forKey: "inicioConfigurado") {
                Inicio.cambiar(true)
                UserDefaults.standard.set(true, forKey: "inicioConfigurado")
            }
        }
    }

    // abrir la app otra vez (Spotlight, Finder) = abrir Ajustes
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        MainActor.assumeIsolated { Barra.shared.abrirAjustes() }
        return false
    }
}
