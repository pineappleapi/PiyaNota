import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/fake_auth_api.dart';
import 'package:piyanota_application/services/fake_score_library_api.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/services/session_storage.dart';

import '../auth/auth_test_harness.dart';

/// Wires the fake library to a real [FakeAuthApi], the way the providers
/// do, so AC1's account scoping is tested end to end through the token.
class _Harness {
  _Harness()
    : auth = FakeAuthApi(latency: Duration.zero),
      secure = FaultySecureStorage() {
    storage = SessionStorage(secure);
    library = FakeScoreLibraryApi(
      sessionStorage: storage,
      accountForToken: auth.accountForToken,
      latency: Duration.zero,
      clock: () => now,
    );
  }

  /// What the fake's clock reads; tests move it.
  DateTime now = DateTime.utc(2026, 10, 8, 9);

  final FakeAuthApi auth;
  final FaultySecureStorage secure;
  late final SessionStorage storage;
  late final FakeScoreLibraryApi library;

  Future<void> logIn(String email, String password) async {
    await storage.save(await auth.login(email: email, password: password));
  }

  Future<void> signUp(String email) async {
    await storage.save(
      await auth.signUp(
        email: email,
        password: 'secret123',
        passwordConfirmation: 'secret123',
      ),
    );
  }
}

void main() {
  test(
    'the demo account sees the mockup scores plus two incomplete ones',
    () async {
      final h = _Harness();
      await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);

      final scores = await h.library.fetchLibrary();
      expect(scores.map((s) => s.title), [
        'Bituin Walang Ningning',
        'Paraiso',
        'Bahay Kubo',
        null,
        'Pasko Na Naman',
      ]);
      final noArranger = scores.last;
      expect(noArranger.arranger, isNull);
      expect(noArranger.pageCount, isNull);
    },
  );

  test(
    'a fresh sign-up sees an empty library, not the demo data (AC1/AC4)',
    () async {
      final h = _Harness();
      await h.signUp('new.member@example.com');
      expect(await h.library.fetchLibrary(), isEmpty);
    },
  );

  test('switching accounts switches libraries', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    await h.library.deleteScore(102);
    await h.signUp('other@example.com');
    expect(await h.library.fetchLibrary(), isEmpty);

    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    expect((await h.library.fetchLibrary()).map((s) => s.scoreId), [
      101,
      103,
      104,
      105,
    ]);
  });

  test('no or unknown token is a 401', () async {
    final h = _Harness();
    await expectLater(
      h.library.fetchLibrary(),
      throwsA(isA<SessionExpiredException>()),
    );
    h.secure.values['session_token'] = 'forged';
    await expectLater(
      h.library.fetchLibrary(),
      throwsA(isA<SessionExpiredException>()),
    );
  });

  test('search is case-insensitive and partial', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    final scores = await h.library.fetchLibrary(query: ' BAHAY ');
    expect(scores.map((s) => s.scoreId), [103]);
  });

  test('search also matches arranger and the displayed date (AC4)', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    Future<List<int>> ids(String q) async =>
        (await h.library.fetchLibrary(query: q)).map((s) => s.scoreId).toList();

    expect(await ids('cayabyab'), [102]);
    expect(await ids('oct 3'), [101]);
    expect(await ids('new score'), [104]);
  });

  test('recordOpened moves the open time so a refetch agrees', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    final when = DateTime.utc(2026, 10, 8, 9, 30);
    h.now = when;
    await h.library.recordOpened(103);

    final scores = await h.library.fetchLibrary();
    expect(scores.firstWhere((s) => s.scoreId == 103).lastActivityAt, when);
  });

  test('deleting an unknown id is a 404', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    await expectLater(
      h.library.deleteScore(999),
      throwsA(isA<ScoreNotFoundException>()),
    );
  });

  test(
    'flaky accounts fail every odd call so error states can be demoed',
    () async {
      final h = _Harness();
      await h.signUp('tester${FakeScoreLibraryApi.flakyDomain}');

      await expectLater(
        h.library.fetchLibrary(),
        throwsA(isA<ScoreLibraryServerException>()),
      );
      expect(
        await h.library.fetchLibrary(),
        hasLength(FakeScoreLibraryApi.demoScores.length),
      );

      await expectLater(
        h.library.deleteScore(101),
        throwsA(isA<ScoreLibraryServerException>()),
      );
      await h.library.deleteScore(101);
      // Third fetch fails again; the fourth shows the delete stuck.
      await expectLater(
        h.library.fetchLibrary(),
        throwsA(isA<ScoreLibraryServerException>()),
      );
      expect(
        await h.library.fetchLibrary(),
        hasLength(FakeScoreLibraryApi.demoScores.length - 1),
      );
    },
  );
}
