import CoreImage
import Foundation
import Metal

struct RenderError: Error, CustomStringConvertible {
    let description: String
    init(_ message: String) { description = message }
}

func render() throws {
    let arguments = CommandLine.arguments
    guard arguments.count == 7, let rawEV = Float(arguments[4]), rawEV.isFinite else {
        throw RenderError("参数应为资源目录、RAW、参数 JSON、RAW 曝光、基准曝光和输出缓冲路径")
    }
    guard let device = MTLCreateSystemDefaultDevice() else { throw RenderError("找不到 Metal 设备") }
    guard let engine = spk_engine_create(arguments[1], Unmanaged.passUnretained(device).toOpaque()) else {
        throw RenderError(String(cString: spk_last_error(nil)))
    }
    defer { spk_engine_destroy(engine) }

    let input = URL(fileURLWithPath: arguments[2])
    guard let filter = CIRAWFilter(imageURL: input) else { throw RenderError("Core Image 无法解码 \(input.lastPathComponent)") }
    let sourceBaseline = filter.baselineExposure
    if arguments[5] != "source" {
        guard let baseline = Float(arguments[5]), baseline.isFinite else { throw RenderError("无效的基准曝光") }
        filter.baselineExposure = baseline
    }
    // 沿用上游线性 RAW 解码，保留拍摄白平衡和文件基准曝光。
    filter.exposure = rawEV
    filter.shadowBias = 0
    filter.boostAmount = 0
    filter.boostShadowAmount = 0
    filter.isGamutMappingEnabled = false
    filter.localToneMapAmount = 0
    filter.extendedDynamicRangeAmount = 0
    filter.isLensCorrectionEnabled = false
    guard let image = filter.outputImage else { throw RenderError("RAW 解码没有返回图像") }

    let extent = image.extent.integral
    let width = Int(extent.width), height = Int(extent.height)
    let rowBytes = width * 16
    guard width > 0, height > 0, rowBytes * height <= device.maxBufferLength,
          let buffer = device.makeBuffer(length: rowBytes * height, options: .storageModeShared) else {
        throw RenderError("无法为 RAW 解码分配 \(width)×\(height) 的 Metal 缓冲区")
    }
    let working = CGColorSpace(name: CGColorSpace.extendedLinearSRGB)!
    let proPhoto = CGColorSpace(calibratedRGBWhitePoint: [0.9642, 1, 0.8249], blackPoint: [0, 0, 0],
        gamma: [1, 1, 1], matrix: [0.7976749, 0.2880402, 0, 0.1351917, 0.7118741, 0, 0.0313534, 0.0000857, 0.8252100])!
    let context = CIContext(mtlDevice: device, options: [
        .workingColorSpace: working, .workingFormat: CIFormat.RGBAh,
        .cacheIntermediates: false, .highQualityDownsample: true,
    ])
    let placed = image.transformed(by: .init(translationX: -extent.origin.x, y: -extent.origin.y))
    // Core Image 坐标向上，缓冲区按顶行到末行写入。
    let bands = max(1, (width * height + 3_999_999) / 4_000_000)
    for band in 0..<bands {
        autoreleasepool {
            let start = height * band / bands, end = height * (band + 1) / bands
            context.render(placed, toBitmap: buffer.contents() + start * rowBytes, rowBytes: rowBytes,
                           bounds: CGRect(x: 0, y: height - end, width: width, height: end - start),
                           format: .RGBAf, colorSpace: proPhoto)
        }
    }
    context.clearCaches()

    var frame = spk_device_image(buffer: Unmanaged.passUnretained(buffer).toOpaque(),
        width: UInt32(width), height: UInt32(height), channels: 4)
    let delta = try String(contentsOfFile: arguments[3], encoding: .utf8)
    var opened: UnsafeMutablePointer<CChar>?
    guard let session = withExtendedLifetime(buffer, { spk_open_device(engine, &frame, delta, &opened) }) else {
        throw RenderError(String(cString: spk_last_error(engine)))
    }
    defer { spk_session_release(session) }
    defer { spk_string_free(opened) }
    guard let opened else { throw RenderError("SpektraLab 未返回已解析的参数") }
    let readback = try JSONSerialization.jsonObject(with: Data(String(cString: opened).utf8))
    var result = spk_result()
    guard spk_render(session, "full", &result) == SPK_OK else {
        throw RenderError(String(cString: spk_last_error(engine)))
    }
    defer { spk_result_free(&result) }
    guard result.width == width, result.height == height, result.row_stride_px >= result.width,
          let pixels = result.rgba16 else { throw RenderError("渲染输出改变了原始尺寸或没有返回像素") }
    let bytes = Int(result.row_stride_px) * height * 8
    try Data(bytesNoCopy: UnsafeMutableRawPointer(mutating: pixels), count: bytes, deallocator: .none)
        .write(to: URL(fileURLWithPath: arguments[6]))
    let report: [String: Any] = ["width": width, "height": height, "row_stride_px": result.row_stride_px,
        "neutral_temperature": filter.neutralTemperature, "neutral_tint": filter.neutralTint,
        "source_baseline_exposure_ev": sourceBaseline, "baseline_exposure_ev": filter.baselineExposure, "raw_exposure_ev": rawEV,
        "decoder": filter.decoderVersion.rawValue, "raw_orientation": filter.orientation.rawValue,
        "render_ms": result.elapsed_ms, "engine": String(cString: spk_build_info()), "open": readback]
    let json = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
    print(String(decoding: json, as: UTF8.self))
}

do {
    try render()
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
