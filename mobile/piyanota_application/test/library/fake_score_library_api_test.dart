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
    );
  }

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
  test('the demo account sees the three mockup scores (AC1)', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);

    final scores = await h.library.fetchLibrary();
    expect(scores.map((s) => s.title), [
      'Bituin Walang Ningning',
      'Paraiso',
      'Bahay Kubo',
    ]);
  });

  test('a fresh sign-up sees an empty library, not the demo data (AC1/AC4)',
      () async {
    final h = _Harness();
    await h.signUp('new.member@example.com');
    expect(await h.library.fetchLibrary(), isEmpty);
  });

  test('switching accounts switches libraries', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    await h.library.deleteScore(102);
    await h.signUp('other@example.com');
    expect(await h.library.fetchLibrary(), isEmpty);

    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    expect((await h.library.fetchLibrary()).map((s) => s.scoreId), [101, 103]);
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

  test('deleting an unknown id is a 404', () async {
    final h = _Harness();
    await h.logIn(FakeAuthApi.demoEmail, FakeAuthApi.demoPassword);
    await expectLater(
      h.library.deleteScore(999),
      throwsA(isA<ScoreNotFoundException>()),
    );
  });

  test('flaky accounts fail every odd call so error states can be demoed',
      () async {
    final h = _Harness();
    await h.signUp('tester${FakeScoreLibraryApi.flakyDomain}');

    await expectLater(
      h.library.fetchLibrary(),
      throwsA(isA<ScoreLibraryServerException>()),
    );
    expect(await h.library.fetchLibrary(), hasLength(3));

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
    expect(await h.library.fetchLibrary(), hasLength(2));
  });
}
