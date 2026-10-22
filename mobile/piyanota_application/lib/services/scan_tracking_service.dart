import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// The device half of following conversions in the background (PIYA-218,
/// user decision 2026-10-22). While [show] is in force a foreground
/// service keeps the app alive with a "Scanning <title>…" notification,
/// so the tracker's own poll keeps running when the user leaves the app;
/// [notifyResult] posts the system notification for a scan that finished
/// while the app was not on screen.
///
/// Nothing here throws: losing a notification must never stop a scan
/// being followed, or a logout.
abstract interface class ScanTrackingService {
  /// Starts the service, or changes its notification's words.
  Future<void> show(String text);

  /// Nothing left to follow.
  Future<void> stop();

  /// [ok] is true for a scan that is ready, false for one that failed.
  Future<void> notifyResult({
    required String jobId,
    required String title,
    required String text,
    required bool ok,
  });

  /// The result has been seen in the app, or the job forgotten.
  Future<void> clearResult(String jobId);

  /// Logout: the service and every conversion notification go.
  Future<void> stopAll();

  /// Job ids of tapped result notifications.
  Stream<String> get opened;
}

class MethodChannelScanTrackingService implements ScanTrackingService {
  MethodChannelScanTrackingService([MethodChannel? channel])
    : _channel = channel ?? const MethodChannel('piyanota/scans') {
    _channel.setMethodCallHandler(_onCall);
  }

  final MethodChannel _channel;
  final StreamController<String> _opened = StreamController.broadcast();

  Future<void> _onCall(MethodCall call) async {
    if (call.method != 'open') return;
    final arguments = call.arguments;
    final jobId = arguments is Map ? arguments['jobId'] : null;
    if (jobId is String) _opened.add(jobId);
  }

  @override
  Stream<String> get opened => _opened.stream;

  @override
  Future<void> show(String text) => _quietly('show', {'text': text});

  @override
  Future<void> stop() => _quietly('stop');

  @override
  Future<void> notifyResult({
    required String jobId,
    required String title,
    required String text,
    required bool ok,
  }) => _quietly('notifyResult', {
    'jobId': jobId,
    'title': title,
    'text': text,
    'ok': ok,
  });

  @override
  Future<void> clearResult(String jobId) =>
      _quietly('clearResult', {'jobId': jobId});

  @override
  Future<void> stopAll() => _quietly('stopAll');

  Future<void> _quietly(
    String method, [
    Map<String, Object?>? arguments,
  ]) async {
    try {
      await _channel.invokeMethod<void>(method, arguments);
    } on PlatformException catch (e) {
      debugPrint('Scan tracking: $method failed: $e');
    } on MissingPluginException catch (e) {
      // Tests and platforms without the native side.
      debugPrint('Scan tracking: $method unavailable: $e');
    }
  }
}
