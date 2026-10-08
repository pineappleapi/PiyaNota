import 'package:camera/camera.dart';
import 'package:flutter/widgets.dart';

/// The device has no usable back camera (or it failed to open).
class CameraUnavailableException implements Exception {
  const CameraUnavailableException();
}

/// The live camera behind Capture, wrapped so widget tests run without
/// hardware. One instance per preview session: the screen disposes it when
/// the app goes to the background and makes a new one on return, as the
/// camera plugin requires.
abstract interface class CaptureCamera {
  /// Throws [CameraUnavailableException].
  Future<void> initialize();

  /// Width / height of the preview in portrait.
  double get previewAspectRatio;

  Widget buildPreview();

  Future<void> setTorch({required bool on});

  /// [point] is normalised 0–1 within the preview.
  Future<void> focusAt(Offset point);

  /// Path of the captured JPEG.
  Future<String> takePicture();

  Future<void> dispose();
}

typedef CaptureCameraFactory = CaptureCamera Function();

class PluginCaptureCamera implements CaptureCamera {
  CameraController? _controller;

  @override
  Future<void> initialize() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) throw const CameraUnavailableException();
      final back = cameras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      // veryHigh (1080p-class) keeps small noteheads legible without the
      // memory cost of max; prepare() still caps uploads at 4032 px.
      final controller = CameraController(
        back,
        ResolutionPreset.veryHigh,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );
      _controller = controller;
      await controller.initialize();
      await controller.setFlashMode(FlashMode.off);
    } on CameraException {
      throw const CameraUnavailableException();
    }
  }

  CameraController get _ready {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      throw const CameraUnavailableException();
    }
    return controller;
  }

  @override
  double get previewAspectRatio => 1 / _ready.value.aspectRatio;

  @override
  Widget buildPreview() => CameraPreview(_ready);

  @override
  Future<void> setTorch({required bool on}) =>
      _ready.setFlashMode(on ? FlashMode.torch : FlashMode.off);

  @override
  Future<void> focusAt(Offset point) async {
    final controller = _ready;
    try {
      if (controller.value.focusPointSupported) {
        await controller.setFocusPoint(point);
      }
      if (controller.value.exposurePointSupported) {
        await controller.setExposurePoint(point);
      }
    } on CameraException {
      // Tap-to-focus is a nicety; a lens that refuses it still captures.
    }
  }

  @override
  Future<String> takePicture() async {
    try {
      final file = await _ready.takePicture();
      return file.path;
    } on CameraException {
      throw const CameraUnavailableException();
    }
  }

  @override
  Future<void> dispose() async {
    final controller = _controller;
    _controller = null;
    await controller?.dispose();
  }
}
