import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'capture/device_channel.dart';

/// Android 13+'s POST_NOTIFICATIONS, asked once, the first time the app
/// has something to show in the notification shade (an export, PIYA-211,
/// or a conversion left running, PIYA-218; user decision 2026-10-22).
/// Refusing it changes nothing but the notifications: the export or the
/// conversion still runs.
abstract interface class NotificationPermission {
  /// The app should explain and ask now: Android 13+, not granted, and
  /// not asked before.
  Future<bool> shouldAsk();

  /// Records that the user has been asked, whatever they answer, so the
  /// explanation is never shown twice.
  Future<void> markAsked();

  /// Shows the system prompt.
  Future<void> request();
}

class PluginNotificationPermission implements NotificationPermission {
  PluginNotificationPermission(this._device);

  final DeviceChannel _device;

  /// Android 13 (Tiramisu), where notifications became a runtime permission.
  static const int _runtimePermissionSdk = 33;
  static const String _askedKey = 'notifications_asked_v1';

  @override
  Future<bool> shouldAsk() async {
    try {
      if (await _device.sdkInt() < _runtimePermissionSdk) return false;
      final prefs = await SharedPreferences.getInstance();
      if (prefs.getBool(_askedKey) ?? false) return false;
      return !await Permission.notification.isGranted;
    } on PlatformException catch (e) {
      // Not asking only costs the notification; the work still runs.
      debugPrint('Notifications: could not tell whether to ask: $e');
      return false;
    } on MissingPluginException catch (e) {
      debugPrint('Notifications: permission check unavailable: $e');
      return false;
    }
  }

  @override
  Future<void> markAsked() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_askedKey, true);
    } on PlatformException catch (e) {
      debugPrint('Notifications: asked flag not saved: $e');
    } on MissingPluginException catch (e) {
      debugPrint('Notifications: asked flag unavailable: $e');
    }
  }

  @override
  Future<void> request() async {
    try {
      await Permission.notification.request();
    } on PlatformException catch (e) {
      debugPrint('Notifications: permission request failed: $e');
    } on MissingPluginException catch (e) {
      debugPrint('Notifications: permission request unavailable: $e');
    }
  }
}
