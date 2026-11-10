import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'scan_notification_payload.dart';

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

  /// The job of the result notification whose tap started the app (a cold
  /// start, which [opened] can't report: Dart wasn't listening yet), or
  /// null. Taken once, so it never opens twice (PIYA-202-V2.2 AC5).
  Future<String?> takeLaunchJob();

  /// The service went without being asked (Android 15+'s daily timeout,
  /// or a refused start): what was last [show]n is no longer up.
  Stream<void> get stopped;
}

class MethodChannelScanTrackingService implements ScanTrackingService {
  MethodChannelScanTrackingService([MethodChannel? channel])
    : _channel = channel ?? const MethodChannel('piyanota/scans') {
    _channel.setMethodCallHandler(_onCall);
  }

  final MethodChannel _channel;
  final StreamController<String> _opened = StreamController.broadcast();
  final StreamController<void> _stopped = StreamController.broadcast();

  Future<void> _onCall(MethodCall call) async {
    if (call.method == 'stopped') {
      _stopped.add(null);
      return;
    }
    if (call.method != 'open') return;
    final arguments = call.arguments;
    final jobId = arguments is Map ? arguments['jobId'] : null;
    // Raw on purpose: the router parses it, so a malformed payload still
    // brings the user to the Library instead of doing nothing.
    _opened.add(jobId is String ? jobId : '');
  }

  @override
  Stream<String> get opened => _opened.stream;

  @override
  Stream<void> get stopped => _stopped.stream;

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
  }) {
    final payload = ScanNotificationPayload.build(jobId);
    if (payload == null) {
      debugPrint('Scan tracking: not notifying, unusable job id');
      return Future.value();
    }
    return _quietly('notifyResult', {
      'jobId': payload,
      'title': title,
      'text': text,
      'ok': ok,
    });
  }

  @override
  Future<void> clearResult(String jobId) =>
      _quietly('clearResult', {'jobId': jobId});

  @override
  Future<void> stopAll() => _quietly('stopAll');

  @override
  Future<String?> takeLaunchJob() async {
    try {
      return await _channel.invokeMethod<String>('takeLaunchJob');
    } on PlatformException catch (e) {
      debugPrint('Scan tracking: takeLaunchJob failed: $e');
    } on MissingPluginException catch (e) {
      // Tests and platforms without the native side.
      debugPrint('Scan tracking: takeLaunchJob unavailable: $e');
    }
    return null;
  }

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
