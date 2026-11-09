import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/state/score_library_providers.dart';

class _Api implements ScoreLibraryApi {
  _Api(this.fetch);
  Future<List<ScoreSummary>> Function() fetch;
  int calls = 0;

  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) {
    calls++;
    return fetch();
  }

  @override
  Future<void> deleteScore(int scoreId) async {}
  @override
  Future<ScoreSummary> updateScore(
    int scoreId, {
    required String title,
    String? arranger,
  }) async => ScoreSummary(scoreId: scoreId, title: title);
  @override
  Future<void> recordOpened(int scoreId) async {}
}

void main() {
  const stored = ScoreSummary(
    scoreId: 7,
    title: 'Paraiso',
    arranger: 'A. Cruz',
    pageCount: 3,
  );
  const server = ScoreSummary(scoreId: 8, title: 'Fresh');

  ProviderContainer make(_Api api) {
    final c = ProviderContainer(
      overrides: [scoreLibraryApiProvider.overrideWithValue(api)],
    );
    addTearDown(c.dispose);
    // autoDispose: hold it open like the mounted screen does.
    c.listen(scoreLibraryProvider, (_, _) {});
    return c;
  }

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({'session_email': 'a@b.c'});
  });

  Future<void> seedCache() async {
    SharedPreferences.setMockInitialValues({});
    final seed = make(_Api(() async => [stored]));
    await seed.read(scoreLibraryProvider.future);
    await pumpEventQueue();
  }

  test('cache-first: stored list renders before the network answers', () async {
    await seedCache();
    final gate = Completer<List<ScoreSummary>>();
    final api = _Api(() => gate.future);
    final c = make(api);
    final first = await c.read(scoreLibraryProvider.future);
    expect(first.single.title, 'Paraiso');
    expect(first.single.arranger, 'A. Cruz');
    await pumpEventQueue();
    expect(api.calls, 1); // background refresh started
    gate.complete([server]);
    await pumpEventQueue();
    expect(c.read(scoreLibraryProvider).value!.single.scoreId, 8);
  });

  test('a local change drops an older in-flight background refresh', () async {
    await seedCache();
    final gate = Completer<List<ScoreSummary>>();
    final c = make(_Api(() => gate.future));
    await c.read(scoreLibraryProvider.future);
    await pumpEventQueue();
    c.read(scoreLibraryProvider.notifier).removeLocally(7);
    gate.complete([stored, server]);
    await pumpEventQueue();
    expect(c.read(scoreLibraryProvider).value, isEmpty);
  });

  test('offline: failed background refresh keeps the cached list', () async {
    await seedCache();
    final c = make(
      _Api(() async => throw const ScoreLibraryNetworkException()),
    );
    await c.read(scoreLibraryProvider.future);
    await pumpEventQueue();
    final s = c.read(scoreLibraryProvider);
    expect(s.hasError, isFalse);
    expect(s.value!.single.scoreId, 7);
  });

  test('error only when nothing is stored and the fetch fails', () async {
    SharedPreferences.setMockInitialValues({});
    final c = make(
      _Api(() async => throw const ScoreLibraryNetworkException()),
    );
    final sub = c.listen(scoreLibraryProvider, (_, _) {});
    addTearDown(sub.close);
    await pumpEventQueue();
    expect(c.read(scoreLibraryProvider).hasError, isTrue);
  });
}
