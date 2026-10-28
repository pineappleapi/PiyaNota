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

    Future<void> confirm(FakeAuthApi api, String code) =>
        api.confirmPasswordReset(
          resetToken: code,
          newPassword: newPassword,
          newPasswordConfirmation: newPassword,
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

    test('unknown code is a wrong code (400), not an expired one', () {
      expect(
        confirm(_api(), '000000'),
        throwsA(isA<ResetCodeWrongException>()),
      );
    });

    test(
      '4th wrong code onwards is rate limited, doubling from 30 s',
      () async {
        var now = DateTime.utc(2026, 10, 28, 9);
        final api = FakeAuthApi(latency: Duration.zero, clock: () => now);
        await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
        final good = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;
        for (var i = 0; i < 3; i++) {
          await expectLater(
            confirm(api, '000000'),
            throwsA(isA<ResetCodeWrongException>()),
          );
        }
        await expectLater(
          confirm(api, '000000'),
          throwsA(
            isA<AuthRateLimitedException>().having(
              (e) => e.retryAfterSeconds,
              'retryAfterSeconds',
              30,
            ),
          ),
        );
        // Even the right code waits, so the limit can't be guessed around.
        await expectLater(
          confirm(api, good),
          throwsA(isA<AuthRateLimitedException>()),
        );
        now = now.add(const Duration(seconds: 30));
        await expectLater(
          confirm(api, '000000'),
          throwsA(
            isA<AuthRateLimitedException>().having(
              (e) => e.retryAfterSeconds,
              'retryAfterSeconds',
              60,
            ),
          ),
        );
      },
    );

    test('a new code request resets the wrong-code count', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      for (var i = 0; i < 4; i++) {
        await confirm(api, '000000').then((_) {}, onError: (_) {});
      }
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      await expectLater(
        confirm(api, '000000'),
        throwsA(isA<ResetCodeWrongException>()),
      );
    });

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
      await expectLater(
        confirm(api, first),
        throwsA(isA<ResetCodeInvalidException>()),
      );
      await confirm(api, second);
    });

    test('weak password is a 400 and does not consume the code', () async {
      final api = _api();
      await api.requestPasswordReset(email: FakeAuthApi.demoEmail);
      final code = api.demoInboxCodeFor(FakeAuthApi.demoEmail)!;

      await expectLater(
        api.confirmPasswordReset(
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
}
