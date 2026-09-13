// Native Apple Vision framework OCR runner for mobile-mcp (macOS)
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1 else {
    print("[]")
    exit(0)
}

let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("[]")
    exit(0)
}

let pixelWidth = Double(cgImage.width)
let pixelHeight = Double(cgImage.height)

// Infer standard iOS Retina scale factor (3x for Pro/Plus devices, 2x for standard/SE, 1x fallback)
let scaleFactor: Double
if pixelWidth >= 1100 || pixelHeight >= 2400 {
    scaleFactor = 3.0
} else if pixelWidth >= 640 || pixelHeight >= 1136 {
    scaleFactor = 2.0
} else {
    scaleFactor = 1.0
}

let pointWidth = pixelWidth / scaleFactor
let pointHeight = pixelHeight / scaleFactor

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try? handler.perform([request])

guard let results = request.results else {
    print("[]")
    exit(0)
}

struct ElementBounds: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ElementPoint: Codable {
    let x: Double
    let y: Double
}

struct LayoutElement: Codable {
    let index: Int
    let text: String
    let confidence: Float
    let pixel_bounds: ElementBounds
    let pixel_center: ElementPoint
    let point_bounds: ElementBounds
    let point_center: ElementPoint
}

var elements: [LayoutElement] = []
var index = 1

for observation in results {
    guard let candidate = observation.topCandidates(1).first else { continue }
    let box = observation.boundingBox
    
    // Pixel coordinates (top-left origin)
    let px = box.origin.x * pixelWidth
    let py = (1.0 - box.origin.y - box.size.height) * pixelHeight
    let pw = box.size.width * pixelWidth
    let ph = box.size.height * pixelHeight
    let pcx = px + (pw / 2.0)
    let pcy = py + (ph / 2.0)
    
    // Point coordinates (top-left origin)
    let ptx = px / scaleFactor
    let pty = py / scaleFactor
    let ptw = pw / scaleFactor
    let pth = ph / scaleFactor
    let ptcx = pcx / scaleFactor
    let ptcy = pcy / scaleFactor
    
    let el = LayoutElement(
        index: index,
        text: candidate.string,
        confidence: candidate.confidence,
        pixel_bounds: ElementBounds(x: round(px), y: round(py), width: round(pw), height: round(ph)),
        pixel_center: ElementPoint(x: round(pcx), y: round(pcy)),
        point_bounds: ElementBounds(x: round(ptx), y: round(pty), width: round(ptw), height: round(pth)),
        point_center: ElementPoint(x: round(ptcx), y: round(ptcy))
    )
    elements.append(el)
    index += 1
}

let encoder = JSONEncoder()
encoder.outputFormatting = .prettyPrinted
if let data = try? encoder.encode(elements), let str = String(data: data, encoding: .utf8) {
    print(str)
} else {
    print("[]")
}
