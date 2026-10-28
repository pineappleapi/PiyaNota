import 'dart:math';

import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/services/auth_api.dart';
import 'package:piyanota_application/services/fake_auth_api.dart';

FakeAuthApi _api() => FakeAuthApi(latency: Duration.zero);

void main() {
  test('demo credentials log in, case-insensitively on email', () async {
    final session = await _api().login(
      email: '  Demo@PiyaNota.app ',
      password: FakeAuthApi.demoPassword,
    );
    expect(session.email, FakeAuthApi.demoEmail);
    expect(session.sessionToken, isNotEmpty);
    expect(session.expiresAt.isAfter(DateTime.now().toUtc()), isTrue);
  });

  test('wrong password is a 401', () {
    expect(
      _api().login(email: FakeAuthApi.demoEmail, password: 'nope1234'),
      throwsA(isA<InvalidCredentialsException>()),
    );
  });

  test('offline domain simulates a network failure', () {
    expect(
      _api().login(email: 'a@offline.test', password: 'x'),
      throwsA(isA<AuthNetworkException>()),
    );
  });

  test('sign-up then login with the new account', () async {
    final api = _api();
    await api.signUp(
      email: 'new@example.com',
      password: 'secret123',
      passwordConfirmation: 'secret123',
    );
    final session = await api.login(
      email: 'new@example.com',
      password: 'secret123',
    );
    expect(session.email, 'new@example.com');
  });

  test('registered email is a 409', () {
    expect(
      _api().signUp(
        email: 'DEMO@piyanota.app',
        password: 'secret123',
        passwordConfirmation: 'secret123',
      ),
      throwsA(isA<EmailAlreadyRegisteredException>()),
    );
  });

  test('weak or mismatched password is a 400', () {
    final api = _api();
    expect(
      api.signUp(
        email: 'a@example.com',
        password: 'short',
        passwordConfirmation: 'short',
      ),
      throwsA(isA<AuthValidationException>()),
    );
    expect(
      api.signUp(
        email: 'b@example.com',
        password: 'secret123',
        passwordConfirmation: 'secret124',
      ),
      throwsA(isA<AuthValidationException>()),
    );
  });

  group('login wait (PIYA-202-V2.1 AC7)', () {
    Matcher rateLimited(int seconds) => throwsA(
      isA<AuthRateLimitedException>().having(
        (e) => e.retryAfterSeconds,
        'retryAfterSeconds',
        seconds,
      ),
    );

    test('repeated wrong logins are limited on the 30 s doubling', () async {
      var now = DateTime.utc(2026, 10, 28, 9);
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      Future<void> wrong() =>
          api.login(email: FakeAuthApi.demoEmail, password: 'nope');

      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      await expectLater(wrong(), rateLimited(30));
      now = now.add(const Duration(seconds: 30));
      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      now = now.add(const Duration(seconds: 20));
      await expectLater(wrong(), rateLimited(40));
    });

    test('a completed password reset clears the wait', () async {
      final now = DateTime.utc(2026, 10, 28, 9);
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      await expectLater(
        api.login(email: FakeAuthApi.demoEmail, password: 'nope'),
        throwsA(isA<InvalidCredentialsException>()),
      );
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      await api.confirmPasswordReset(
        email: FakeAuthApi.demoEmail,
        resetToken: api.demoInboxCodeFor(FakeAuthApi.demoEmail)!,
        newPassword: 'Newpass123',
        newPasswordConfirmation: 'Newpass123',
      );

      // Same instant: still inside the 30 s, yet the new password gets in,
      // and the old one is simply wrong again (count restarted).
      await api.login(email: FakeAuthApi.demoEmail, password: 'Newpass123');
      await expectLater(
        api.login(email: FakeAuthApi.demoEmail, password: 'nope'),
        throwsA(isA<InvalidCredentialsException>()),
      );
    });

    test('a correct login after the wait resets the count', () async {
      var now = DateTime.utc(2026, 10, 28, 9);
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      Future<void> wrong() =>
          api.login(email: FakeAuthApi.demoEmail, password: 'nope');

      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      now = now.add(const Duration(seconds: 30));
      await api.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      await expectLater(wrong(), rateLimited(30));
    });
  });

  group('password reset (PIYA-303/304)', () {
    const newPassword = 'choir2026';

    Future<void> confirm(
      FakeAuthApi api,
      String code, {
      String email = FakeAuthApi.demoEmail,
    }) => api.confirmPasswordReset(
      email: email,
      resetToken: code,
      newPassword: newPassword,
      newPasswordConfirmation: newPassword,
    );

    /// A code that is surely not [code], so a "wrong code" never hits it.
    String not(String code) => code == '000000' ? '000001' : '000000';

    Matcher rateLimited(int seconds) => throwsA(
      isA<AuthRateLimitedException>().having(
        (e) => e.retryAfterSeconds,
        'retryAfterSeconds',
        seconds,
      ),
    );

    test(
      'registered email gets a 6-digit code that resets the password',
      () async {
        final api = _api();
        await api.requestPasswordReset(email: ' Demo@PiyaNota.app ');
        final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        expect(code, matches(RegExp(r'^\d{6}$')));

        await confirm(api, code);

        final session = await api.login(
          email: FakeAuthApi.demoEmail,
          password: newPassword,
        );
        expect(session.email, FakeAuthApi.demoEmail);
        await expectLater(
          api.login(
            email: FakeAuthApi.demoEmail,
            password: FakeAuthApi.demoPassword,
          ),
          throwsA(isA<InvalidCredentialsException>()),
        );
      },
    );

    test(
      'unregistered email throws EmailNotRegisteredException and gets no code',
      () async {
        final api = _api();
        await expectLater(
          api.requestPasswordReset(email: 'nobody@example.com'),
          throwsA(isA<EmailNotRegisteredException>()),
        );
        expect(api.demoInboxCodeFor('nobody@example.com'), isNull);
      },
    );

    test(
      'requests are limited to 5 per email per hour, 404s too (B3)',
      () async {
        var now = DateTime.utc(2026, 10, 28, 9);
        final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
        for (var i = 0; i < FakeAuthApi.resetRequestMaxPerEmail; i++) {
          await expectLater(
            api.requestPasswordReset(email: 'nobody@example.com'),
            throwsA(isA<EmailNotRegisteredException>()),
          );
          now = now.add(const Duration(minutes: 1));
        }
        // Checked before the lookup, so the limited caller learns nothing.
        await expectLater(
          api.requestPasswordReset(email: ' Nobody@Example.com '),
          rateLimited(55 * 60),
        );
        // Another email has its own count.
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        now = now.add(const Duration(minutes: 56));
        await expectLater(
          api.requestPasswordReset(email: 'nobody@example.com'),
          throwsA(isA<EmailNotRegisteredException>()),
        );
      },
    );

    test('malformed email is a 400; offline domain is a network failure', () {
      final api = _api();
      expect(
        api.requestPasswordReset(email: 'not-an-email'),
        throwsA(isA<AuthValidationException>()),
      );
      expect(
        api.requestPasswordReset(email: 'a@offline.test'),
        throwsA(isA<AuthNetworkException>()),
      );
    });

    test('code is single use (410 on reuse)', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      await confirm(api, code);
      await expectLater(
        confirm(api, code),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test(
      'a wrong code for a live reset is a 400, not an expired one',
      () async {
        final api = _api();
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        await expectLater(
          confirm(api, not(good)),
          throwsA(isA<ResetCodeWrongException>()),
        );
      },
    );

    test('no live reset for the email is a 410 (B4.3)', () {
      expect(
        confirm(_api(), '000000'),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test('a correct code under a different email is rejected (B4.2)', () async {
      const other = 'ann@example.com';
      final api = FakeAuthApi(latency: Duration.zero, random: Random(7));
      await api.signUp(
        email: other,
        password: newPassword,
        passwordConfirmation: newPassword,
      );
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final demoCode = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      // No reset was requested for the other account.
      await expectLater(
        confirm(api, demoCode, email: other),
        throwsA(isA<ResetCodeInvalidException>()),
      );
      await api.requestPasswordReset(email: other);
      expect(api.demoInboxCodeFor(other), isNot(demoCode));
      // Its reset is live, but the demo's code is not its code.
      await expectLater(
        confirm(api, demoCode, email: other),
        throwsA(isA<ResetCodeWrongException>()),
      );
      await confirm(api, demoCode);
    });

    test(
      'every wrong code is a 400; the 3rd starts a wait of 30 s, 60 s, 120 s',
      () async {
        var now = DateTime.utc(2026, 10, 28, 9);
        final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        Future<void> wrong() => confirm(api, not(good));

        for (var i = 0; i < 2; i++) {
          await expectLater(wrong(), throwsA(isA<ResetCodeWrongException>()));
        }
        // 3rd, 4th and 5th wrong codes: still "wrong", each then a wait.
        for (final seconds in [30, 60, 120]) {
          await expectLater(wrong(), throwsA(isA<ResetCodeWrongException>()));
          // Even the right code waits, and a request during the wait is
          // not counted (B4.5), or the next wait would not double.
          await expectLater(confirm(api, good), rateLimited(seconds));
          await expectLater(wrong(), rateLimited(seconds));
          now = now.add(Duration(seconds: seconds));
        }
        await confirm(api, good);
      },
    );

    test(
      'a new code request does not reset the wrong-code count (B4.6)',
      () async {
        final api = _api();
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        for (var i = 0; i < 2; i++) {
          await confirm(api, '000000').then((_) {}, onError: (_) {});
        }
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        await expectLater(
          confirm(api, not(good)),
          throwsA(isA<ResetCodeWrongException>()),
        );
        await expectLater(confirm(api, good), rateLimited(30));
      },
    );

    test('code expires after resetCodeLifetime', () async {
      var now = DateTime.utc(2026, 10, 8, 9);
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      now = now.add(FakeAuthApi.resetCodeLifetime);
      expect(api.demoInboxCodeFor(FakeAuthApi.demoEmail), isNull);
      await expectLater(
        confirm(api, code),
        throwsA(isA<ResetCodeInvalidException>()),
      );
    });

    test('a new request invalidates the previous unused code', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final first = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final second = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      expect(second, isNot(first));
      // B4.3: a reset is still live, so the old code is just wrong (400).
      await expectLater(
        confirm(api, first),
        throwsA(isA<ResetCodeWrongException>()),
      );
      await confirm(api, second);
    });

    test('weak password is a 400 and does not consume the code', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      await expectLater(
        api.confirmPasswordReset(
          email: FakeAuthApi.demoEmail,
          resetToken: code,
          newPassword: 'short',
          newPasswordConfirmation: 'short',
        ),
        throwsA(isA<AuthValidationException>()),
      );
      await confirm(api, code);
    });
  });

  group('user ids (PIYA-205-V2.3)', () {
    test('the demo account is id 1 on every run', () async {
      final session = await _api().login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      expect(session.userId, FakeAuthApi.demoUserId);
      expect(session.userId, 1);
    });

    test('two logins of one account in a run get the same id', () async {
      final api = _api();
      final first = await api.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      final second = await api.login(
        email: FakeAuthApi.demoEmail,
        password: FakeAuthApi.demoPassword,
      );
      expect(second.userId, first.userId);
      expect(second.sessionToken, isNot(first.sessionToken));
    });

    test('a new sign-up never gets the demo id, and keeps its id', () async {
      final api = _api();
      final signedUp = await api.signUp(
        email: 'ids@example.com',
        password: 'secret123',
        passwordConfirmation: 'secret123',
      );
      final again = await api.login(
        email: 'ids@example.com',
        password: 'secret123',
      );
      expect(signedUp.userId, isNot(1));
      expect(again.userId, signedUp.userId);
    });
  });

  group('24 h reset of wrong counts (B1.4, B4.6)', () {
    const almostDay = Duration(hours: 23, minutes: 59);
    const day = Duration(hours: 24);
    final start = DateTime.utc(2026, 10, 28, 9);

    Matcher rateLimited(int seconds) => throwsA(
      isA<AuthRateLimitedException>().having(
        (e) => e.retryAfterSeconds,
        'retryAfterSeconds',
        seconds,
      ),
    );

    // Wrong login at start, then another [after] later; returns the wait
    // the second one earned.
    Future<void> secondWrongLogin(Duration after, int expectedWait) async {
      var now = start;
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      Future<void> wrong() =>
          api.login(email: FakeAuthApi.demoEmail, password: 'nope');
      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      now = start.add(after);
      await expectLater(wrong(), throwsA(isA<InvalidCredentialsException>()));
      await expectLater(wrong(), rateLimited(expectedWait));
    }

    test('login: 23 h 59 m after the last wrong try the count is kept', () {
      return secondWrongLogin(almostDay, 60);
    });

    test('login: at 24 h the count resets, the first wait comes again', () {
      return secondWrongLogin(day, 30);
    });

    Future<void> secondWrongCode(Duration after, int expectedWait) async {
      var now = start;
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      Future<void> wrong() => api.confirmPasswordReset(
        email: FakeAuthApi.demoEmail,
        resetToken: '000000',
        newPassword: 'choir2026',
        newPasswordConfirmation: 'choir2026',
      );
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      // Two free wrong codes, the 3rd starts the 30 s wait.
      for (var i = 0; i < 3; i++) {
        await expectLater(wrong(), throwsA(isA<ResetCodeWrongException>()));
      }
      now = start.add(after);
      // The earlier code has expired by now; a fresh one keeps the count (B4.6).
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      Future<void> wrongNow() => api.confirmPasswordReset(
        email: FakeAuthApi.demoEmail,
        resetToken: good == '000000' ? '000001' : '000000',
        newPassword: 'choir2026',
        newPasswordConfirmation: 'choir2026',
      );
      await expectLater(wrongNow(), throwsA(isA<ResetCodeWrongException>()));
      await expectLater(wrongNow(), rateLimited(expectedWait));
    }

    test('code: 23 h 59 m after the last wrong code the count is kept', () {
      return secondWrongCode(almostDay, 60);
    });

    test('code: at 24 h the count resets, so 2 more are free again', () async {
      var now = start;
      final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
      Future<void> wrong(String code) => api.confirmPasswordReset(
        email: FakeAuthApi.demoEmail,
        resetToken: code,
        newPassword: 'choir2026',
        newPasswordConfirmation: 'choir2026',
      );
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      for (var i = 0; i < 3; i++) {
        await expectLater(
          wrong('000000'),
          throwsA(isA<ResetCodeWrongException>()),
        );
      }
      now = start.add(day);
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
      final bad = good == '000000' ? '000001' : '000000';
      // Count restarted: wrong #1 and #2 start no wait, #3 waits 30 s.
      await expectLater(wrong(bad), throwsA(isA<ResetCodeWrongException>()));
      await expectLater(wrong(bad), throwsA(isA<ResetCodeWrongException>()));
      await wrong(good);
    });
  });
}
