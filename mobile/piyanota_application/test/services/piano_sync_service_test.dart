import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/services/piano_octave_store.dart';
import 'package:piyanota_application/services/piano_settings_api.dart';
import 'package:piyanota_application/services/piano_sync_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeTimer implements Timer {
  _FakeTimer(this.delay, this.run);
  final Duration delay;
  final void Function() run;
  bool cancelled = false;
  bool fired = false;
  @override
  bool get isActive => !cancelled && !fired;
  @override
  int get tick => fired ? 1 : 0;
  @override
  void cancel() => cancelled = true;
}

/// The fake clock: timers only fire when the test says so.
class _Clock {
  final List<_FakeTimer> timers = [];
  Timer make(Duration d, void Function() run) {
    final t = _FakeTimer(d, run);
    timers.add(t);
    return t;
  }

  Future<void> fireLast() async {
    final t = timers.lastWhere((t) => t.isActive);
    t.fired = true;
    t.run();
    await pumpEventQueue();
  }
}

final _t1 = DateTime.utc(2026, 11, 10, 9);
final _t2 = DateTime.utc(2026, 11, 10, 10);

void main() {
  late PianoOctaveStore store;
  late FakePianoSettingsApi api;
  late _Clock clock;
  late PianoSyncService sync;
  var expired = 0;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    store = PianoOctaveStore();
    api = FakePianoSettingsApi();
    clock = _Clock();
    expired = 0;
    sync = PianoSyncService(
      api: api,
      store: store,
      onSessionExpired: () => expired++,
      timer: clock.make,
    )..voice = VoicePart.tenor;
  });

  test('server newer: adopts into local storage', () async {
    await store.save(4, now: _t1);
    api
      ..octave = 5
      ..updatedAt = _t2;
    expect(await sync.reconcile(), 5);
    expect((await store.loadSaved())!.octave, 5);
    expect(api.puts, isEmpty);
  });

  test('local newer: PUTs it', () async {
    await store.save(2, now: _t2);
    api
      ..octave = 5
      ..updatedAt = _t1;
    expect(await sync.reconcile(), isNull);
    expect(api.puts.single.octave, 2);
    expect(api.puts.single.at, _t2);
    expect(api.octave, 2);
  });

  test('server default, nothing saved locally: no PUT', () async {
    expect(await sync.reconcile(), isNull);
    expect(api.puts, isEmpty);
  });

  test('server default, user saved: pushes the local value', () async {
    await store.save(6, now: _t1);
    await sync.reconcile();
    expect(api.puts.single.octave, 6);
  });

  test('service passes the voice to the API', () async {
    await store.save(3, now: _t1);
    await sync.reconcile();
    expect(api.puts.single.voice, VoicePart.tenor);
  });

  test('rapid taps debounce into one PUT with the final value', () async {
    for (final o in [3, 4, 5]) {
      await store.save(o, now: _t1.add(Duration(seconds: o)));
      await sync.localChanged();
    }
    expect(clock.timers.where((t) => t.isActive), hasLength(1));
    expect(clock.timers.last.delay, PianoSyncService.debounce);
    expect(api.puts, isEmpty);
    await clock.fireLast();
    expect(api.puts.single.octave, 5);
    expect(await store.isPending(), isFalse);
  });

  test('flush sends before the debounce fires', () async {
    await store.save(5, now: _t1);
    await sync.localChanged();
    await sync.flush();
    expect(api.puts.single.octave, 5);
    expect(clock.timers.last.isActive, isFalse);
  });

  test('flush with nothing pending sends nothing; force sends', () async {
    await store.save(5, now: _t1);
    await sync.flush();
    expect(api.puts, isEmpty);
    await sync.flush(force: true);
    expect(api.puts, hasLength(1));
  });

  test('PUT returns a different octave: adopted locally', () async {
    api
      ..octave = 6
      ..updatedAt = _t2;
    await store.save(3, now: _t1);
    await sync.localChanged();
    await clock.fireLast();
    expect((await store.loadSaved())!.octave, 6);
    expect(await store.isPending(), isFalse);
  });

  test('offline: keeps local, stays pending, retries with backoff', () async {
    api.failure = const PianoSettingsNetworkException();
    await store.save(5, now: _t1);
    await sync.localChanged();
    await clock.fireLast();
    expect(await store.isPending(), isTrue);
    expect((await store.loadSaved())!.octave, 5);
    expect(clock.timers.last.delay, PianoSyncService.retryBase);
    await clock.fireLast();
    expect(clock.timers.last.delay, PianoSyncService.retryBase * 2);
    api.failure = null;
    await clock.fireLast();
    expect(api.octave, 5);
    expect(await store.isPending(), isFalse);
  });

  test('retries stop after the cap', () async {
    api.failure = const PianoSettingsServerException();
    await store.save(5, now: _t1);
    await sync.localChanged();
    for (var i = 0; i <= PianoSyncService.maxRetries; i++) {
      await clock.fireLast();
    }
    expect(clock.timers.where((t) => t.isActive), isEmpty);
    expect(await store.isPending(), isTrue);
  });

  test('400 octave_invalid: logged, not retried, local kept', () async {
    api.failure = const PianoSettingsRejectedException('octave_invalid');
    await store.save(5, now: _t1);
    await sync.localChanged();
    await clock.fireLast();
    expect(clock.timers.where((t) => t.isActive), isEmpty);
    expect(await store.isPending(), isFalse);
    expect((await store.loadSaved())!.octave, 5);
  });

  test('401: session flow signalled, local kept, no retry', () async {
    api.failure = const PianoSettingsSessionExpiredException();
    await store.save(5, now: _t1);
    await sync.localChanged();
    await clock.fireLast();
    expect(expired, 1);
    expect(clock.timers.where((t) => t.isActive), isEmpty);
    expect((await store.loadSaved())!.octave, 5);
  });

  test('GET failure on open never throws and keeps local', () async {
    api.failure = const PianoSettingsNetworkException();
    await store.save(5, now: _t1);
    expect(await sync.reconcile(), isNull);
    expect((await store.loadSaved())!.octave, 5);
  });

  test('HttpPianoSettingsApi.parse reads data and rejects bad bodies', () {
    final ok = HttpPianoSettingsApi.parse({
      'data': {
        'octave': 3,
        'updatedAt': '2026-11-10T09:15:00Z',
        'isDefault': false,
      },
    });
    expect(ok.octave, 3);
    expect(ok.updatedAt, DateTime.utc(2026, 11, 10, 9, 15));
    expect(
      HttpPianoSettingsApi.parse({
        'data': {'octave': 4, 'updatedAt': null, 'isDefault': true},
      }).updatedAt,
      isNull,
    );
    expect(
      () => HttpPianoSettingsApi.parse({
        'data': {'octave': 9},
      }),
      throwsA(isA<PianoSettingsServerException>()),
    );
  });
}
