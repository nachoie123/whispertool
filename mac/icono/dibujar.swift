// Dibuja el icono de WhisperTool: losa grafito con 5 ondas; la central, en coral-ámbar (la voz).
import AppKit
let S: CGFloat = 1024
let img = NSImage(size: NSSize(width: S, height: S))
img.lockFocus()
let ctx = NSGraphicsContext.current!.cgContext
// rejilla de iconos de macOS: losa de 824 px con 100 px de margen
let losa = CGRect(x: 100, y: 100, width: 824, height: 824)
let camino = CGPath(roundedRect: losa, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: -12), blur: 28, color: NSColor.black.withAlphaComponent(0.35).cgColor)
ctx.addPath(camino); ctx.setFillColor(NSColor.black.cgColor); ctx.fillPath()
ctx.restoreGState()
ctx.saveGState()
ctx.addPath(camino); ctx.clip()
let fondo = CGGradient(colorsSpace: nil, colors: [NSColor(red: 0.20, green: 0.21, blue: 0.25, alpha: 1).cgColor,
                                                  NSColor(red: 0.06, green: 0.065, blue: 0.08, alpha: 1).cgColor] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(fondo, start: CGPoint(x: 0, y: 924), end: CGPoint(x: 0, y: 100), options: [])
// brillo cálido detrás de la onda central
let halo = CGGradient(colorsSpace: nil, colors: [NSColor(red: 1, green: 0.45, blue: 0.2, alpha: 0.28).cgColor,
                                                 NSColor(red: 1, green: 0.45, blue: 0.2, alpha: 0).cgColor] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(halo, startCenter: CGPoint(x: 512, y: 512), startRadius: 0, endCenter: CGPoint(x: 512, y: 512), endRadius: 340, options: [])
// filo de luz arriba
ctx.setStrokeColor(NSColor.white.withAlphaComponent(0.10).cgColor); ctx.setLineWidth(4)
ctx.addPath(CGPath(roundedRect: losa.insetBy(dx: 2, dy: 2), cornerWidth: 183, cornerHeight: 183, transform: nil)); ctx.strokePath()
// ondas
let alturas: [CGFloat] = [0.30, 0.56, 0.86, 0.62, 0.36]
let ancho: CGFloat = 62, hueco: CGFloat = 44, maxH: CGFloat = 470
let x0 = 512 - (5 * ancho + 4 * hueco) / 2
for (i, a) in alturas.enumerated() {
    let h = maxH * a
    let r = CGRect(x: x0 + CGFloat(i) * (ancho + hueco), y: 512 - h / 2, width: ancho, height: h)
    let p = CGPath(roundedRect: r, cornerWidth: ancho / 2, cornerHeight: ancho / 2, transform: nil)
    ctx.saveGState(); ctx.addPath(p); ctx.clip()
    let cols = i == 2 ? [NSColor(red: 1, green: 0.74, blue: 0.24, alpha: 1), NSColor(red: 1, green: 0.38, blue: 0.22, alpha: 1)]
                      : [NSColor(white: 1, alpha: 0.98), NSColor(white: 0.82, alpha: 0.95)]
    let g = CGGradient(colorsSpace: nil, colors: cols.map { $0.cgColor } as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(g, start: CGPoint(x: 0, y: r.maxY), end: CGPoint(x: 0, y: r.minY), options: [])
    ctx.restoreGState()
}
ctx.restoreGState()
img.unlockFocus()
let rep = NSBitmapImageRep(data: img.tiffRepresentation!)!
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
