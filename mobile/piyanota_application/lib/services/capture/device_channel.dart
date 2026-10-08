import 'package:flutter/services.dart';

/// Why a PDF couldn't be opened on the device.
enum PdfProblem { encrypted, corrupt }

class PdfUnreadableException implements Exception {
  const PdfUnreadableException(this.problem);
  final PdfProblem problem;
}

/// The two platform facts Capture needs that no plugin gives directly. The
/// Android side is `MainActivity.kt`.
abstract interface class DeviceChannel {
  /// `Build.VERSION.SDK_INT`.
  Future<int> sdkInt();

  /// Pages in the PDF at [path], via Android's `PdfRenderer`. Throws
  /// [PdfUnreadableException] for a password-protected or broken file.
  Future<int> pdfPageCount(String path);
}

class MethodChannelDeviceChannel implements DeviceChannel {
  static const MethodChannel _channel = MethodChannel('piyanota/device');

  int? _sdkInt;

  @override
  Future<int> sdkInt() async =>
      _sdkInt ??= await _channel.invokeMethod<int>('sdkInt') ?? 0;

  @override
  Future<int> pdfPageCount(String path) async {
    try {
      final count = await _channel.invokeMethod<int>('pdfPageCount', {
        'path': path,
      });
      if (count == null) throw const PdfUnreadableException(PdfProblem.corrupt);
      return count;
    } on PlatformException catch (e) {
      throw PdfUnreadableException(
        e.code == 'encrypted' ? PdfProblem.encrypted : PdfProblem.corrupt,
      );
    } on MissingPluginException {
      throw const PdfUnreadableException(PdfProblem.corrupt);
    }
  }
}
