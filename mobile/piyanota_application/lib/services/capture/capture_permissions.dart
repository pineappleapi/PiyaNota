import 'package:permission_handler/permission_handler.dart';

import 'device_channel.dart';

/// Result of asking for a permission, collapsed to what the screen shows.
enum PermissionOutcome {
  granted,

  /// Denied this time; asking again can still show the system dialog.
  denied,

  /// "Don't ask again" (or blocked by policy): only Settings can grant it.
  blocked,
}

/// Camera and gallery permissions for Capture (PIYA-206 AC2, AC3). Asked at
/// first use, never at app start.
abstract interface class CapturePermissions {
  Future<PermissionOutcome> requestCamera();

  /// The camera permission as it stands, without prompting. Used when the
  /// app returns from Settings, so a grant there takes effect at once.
  Future<bool> cameraGranted();

  /// AC3 on Android 13+ is met without any permission: `image_picker` opens
  /// the system photo picker, which grants read access to just the photos
  /// the user taps, so there is nothing to deny. Android 12L and older
  /// still need READ_EXTERNAL_STORAGE (declared with maxSdkVersion 32), and
  /// that is where the denial path applies.
  Future<PermissionOutcome> requestGallery();

  Future<bool> openSettings();
}

class PluginCapturePermissions implements CapturePermissions {
  PluginCapturePermissions(this._device);

  final DeviceChannel _device;

  /// Android 13 (Tiramisu), where the photo picker became permission-less.
  static const int _photoPickerSdk = 33;

  @override
  Future<PermissionOutcome> requestCamera() =>
      _request(Permission.camera);

  @override
  Future<bool> cameraGranted() => Permission.camera.isGranted;

  @override
  Future<PermissionOutcome> requestGallery() async {
    if (await _device.sdkInt() >= _photoPickerSdk) {
      return PermissionOutcome.granted;
    }
    return _request(Permission.storage);
  }

  @override
  Future<bool> openSettings() => openAppSettings();

  Future<PermissionOutcome> _request(Permission permission) async {
    final status = await permission.request();
    return switch (status) {
      // provisional is iOS-only; listed so the switch stays exhaustive.
      PermissionStatus.granted ||
      PermissionStatus.limited ||
      PermissionStatus.provisional => PermissionOutcome.granted,
      PermissionStatus.denied => PermissionOutcome.denied,
      PermissionStatus.permanentlyDenied ||
      PermissionStatus.restricted => PermissionOutcome.blocked,
    };
  }
}
