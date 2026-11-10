import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:piyanota_application/models/voice_part.dart';
import 'package:piyanota_application/screens/playback/piano_modal.dart';
import 'package:piyanota_application/services/piano_octave.dart';
import 'package:piyanota_application/services/piano_octave_store.dart';
import 'package:piyanota_application/services/piano_settings_api.dart';
import 'package:piyanota_application/services/piano_sound.dart';
import 'package:piyanota_application/services/piano_sync_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeSound implements PianoSound {
  final List<String> log = [];
  @override
  void noteOn(int midi, int velocity) => log.add('on $midi');
  @override
  void noteOff(int midi) => log.add('off $midi');
  @override
  void releaseAll() => log.add('all');
}

Future<void> _pump(
  WidgetTester tester,
  PianoSound? sound,
  int octave, {
  PianoSyncService? sync,
}) async {
  await tester.binding.setSurfaceSize(const Size(400, 900));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: Align(
          alignment: Alignment.bottomCenter,
          child: PianoModal(
            initialOctave: octave,
            sound: sound,
            store: PianoOctaveStore(),
            sync: sync,
          ),
        ),
      ),
    ),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('MIDI and default octave rules', () {
    expect(midiForC(4), 60);
    expect(midiForC(2), 36);
    expect(midiForC(6) + 11, 95);
    expect(defaultOctaveFor(VoicePart.tenor), 3);
    expect(defaultOctaveFor(VoicePart.bass), 3);
    expect(defaultOctaveFor(VoicePart.alto), 4);
    expect(defaultOctaveFor(null), 4);
  });

  test('store falls back on corrupt value and saves', () async {
    SharedPreferences.setMockInitialValues({PianoOctaveStore.octaveKey: 9});
    final store = PianoOctaveStore();
    expect(await store.load(VoicePart.tenor), 3);
    await store.save(5);
    expect(await store.load(VoicePart.tenor), 5);
  });

  testWidgets('chevrons change octave, disable at ends', (tester) async {
    await _pump(tester, _FakeSound(), 3);
    expect(find.text('Octave 3'), findsOneWidget);
    await tester.tap(find.byTooltip('Lower octave'));
    await tester.pumpAndSettle();
    expect(find.text('Octave 2'), findsOneWidget);
    final lower = tester.widget<IconButton>(
      find.ancestor(
        of: find.byIcon(Icons.chevron_left_rounded),
        matching: find.byType(IconButton),
      ),
    );
    expect(lower.onPressed, isNull);
  });

  testWidgets('key press plays and releases; C4 label', (tester) async {
    final sound = _FakeSound();
    await _pump(tester, sound, 4);
    expect(find.text('C⁴'), findsOneWidget);
    final g = tester.getCenter(find.text('G'));
    final gesture = await tester.startGesture(g);
    await tester.pump();
    expect(sound.log, contains('on 67'));
    await gesture.up();
    await tester.pump();
    expect(sound.log, contains('off 67'));
  });

  testWidgets('notes chart opens and closes alone', (tester) async {
    await _pump(tester, _FakeSound(), 4);
    await tester.tap(find.byTooltip('Notes chart'));
    await tester.pump();
    expect(find.text('Notes Chart'), findsOneWidget);
    await tester.tap(find.byTooltip('Notes chart'));
    await tester.pump();
    expect(find.text('Notes Chart'), findsOneWidget);
    await tester.tap(find.byTooltip('Close notes chart'));
    await tester.pump();
    expect(find.text('Notes Chart'), findsNothing);
    expect(find.text('Piano'), findsOneWidget);
  });

  testWidgets('no sound shows unavailable note, key still presses', (
    tester,
  ) async {
    await _pump(tester, null, 4);
    expect(find.text('Sound is unavailable on this device.'), findsOneWidget);
    final gesture = await tester.startGesture(tester.getCenter(find.text('D')));
    await tester.pump();
    await gesture.up();
  });

  testWidgets('two fingers on one key: note-off only for the last', (
    tester,
  ) async {
    final sound = _FakeSound();
    await _pump(tester, sound, 4);
    final g = tester.getCenter(find.text('G'));
    final a = await tester.startGesture(g, pointer: 1);
    final b = await tester.startGesture(g, pointer: 2);
    await tester.pump();
    expect(sound.log.where((e) => e == 'on 67').length, 1);
    await a.up();
    await tester.pump();
    expect(sound.log, isNot(contains('off 67')));
    await b.up();
    await tester.pump();
    expect(sound.log.where((e) => e == 'off 67').length, 1);
  });

  testWidgets('close without a change keeps the saved timestamp', (
    tester,
  ) async {
    final t = DateTime.utc(2026, 11, 1);
    final store = PianoOctaveStore();
    await store.save(3, now: t);
    final api = FakePianoSettingsApi(octave: 3, updatedAt: t);
    final sync = PianoSyncService(api: api, store: store);
    await _pump(tester, _FakeSound(), 3, sync: sync);
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    expect((await store.loadSaved())!.updatedAt, t);
    expect(api.puts, isEmpty);
  });

  testWidgets('close before reconcile ends does not stamp a default', (
    tester,
  ) async {
    final store = PianoOctaveStore();
    final api = FakePianoSettingsApi(
      octave: 5,
      updatedAt: DateTime.utc(2026, 11, 1),
    );
    final sync = PianoSyncService(api: api, store: store);
    await _pump(tester, _FakeSound(), 4, sync: sync);
    await tester.pumpWidget(const SizedBox()); // closed before the GET lands
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    final saved = await tester.runAsync(store.loadSaved);
    expect(saved?.octave, isNot(4));
    expect(api.puts, isEmpty);
  });

  testWidgets('octave step marks pending, close flushes the PUT', (
    tester,
  ) async {
    final api = FakePianoSettingsApi();
    final store = PianoOctaveStore();
    final sync = PianoSyncService(api: api, store: store);
    await _pump(tester, _FakeSound(), 4, sync: sync);
    await tester.tap(find.byTooltip('Higher octave'));
    await tester.pump();
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    expect(await tester.runAsync(store.isPending), isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    expect(api.puts.single.octave, 5);
    expect(await tester.runAsync(store.isPending), isFalse);
  });
}
