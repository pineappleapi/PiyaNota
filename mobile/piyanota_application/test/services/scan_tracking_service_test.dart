import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/scan_tracking_service.dart';

/// The "piyanota/scans" protocol (PIYA-218) as the Kotlin ScanChannel
/// reads it.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('piyanota/scans');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final calls = <MethodCall>[];

  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
    calls.clear();
  });

  void answer([Object? Function(MethodCall)? reply]) =>
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        return reply?.call(call);
      });

  test('sends what the native side reads', () async {
    answer();
    final service = MethodChannelScanTrackingService();
    await service.show('Converting Paraiso…');
    await service.notifyResult(
      jobId: 'a',
      title: 'Paraiso is ready.',
      text: 'Tap to play it.',
      ok: true,
    );
    await service.clearResult('a');
    await service.stop();
    await service.stopAll();
    expect(
      [for (final c in calls) c.method],
      ['show', 'notifyResult', 'clearResult', 'stop', 'stopAll'],
    );
    expect(calls[0].arguments, {'text': 'Converting Paraiso…'});
    expect(calls[1].arguments, {
      'jobId': 'a',
      'title': 'Paraiso is ready.',
      'text': 'Tap to play it.',
      'ok': true,
    });
    expect(calls[2].arguments, {'jobId': 'a'});
  });

  test('a native stopped() call reaches Dart (review M1)', () async {
    answer();
    final service = MethodChannelScanTrackingService();
    final stops = <void>[];
    final sub = service.stopped.listen(stops.add);
    await messenger.handlePlatformMessage(
      channel.name,
      channel.codec.encodeMethodCall(const MethodCall('stopped')),
      (_) {},
    );
    await Future<void>.delayed(Duration.zero);
    expect(stops, hasLength(1));
    await sub.cancel();
  });

  test('never throws: a native error or no native side is swallowed', () async {
    answer((_) => throw PlatformException(code: 'boom'));
    final service = MethodChannelScanTrackingService();
    await service.show('x');
    await service.stopAll();
    messenger.setMockMethodCallHandler(channel, null);
    await service.stop();
  });

  test('a tapped notification arrives as its job id', () async {
    final service = MethodChannelScanTrackingService();
    final opened = <String>[];
    service.opened.listen(opened.add);
    Future<void> send(Object? arguments) => messenger.handlePlatformMessage(
      channel.name,
      channel.codec.encodeMethodCall(MethodCall('open', arguments)),
      (_) {},
    );
    await send({'jobId': 'a'});
    await send({'nope': 1});
    await send(null);
    await Future<void>.delayed(Duration.zero);
    expect(opened, ['a']);
  });
}
